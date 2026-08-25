from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

from pc_stat_win.categories import (
    ALL_CATEGORY_KEYS,
    normalize_legacy_category,
    resolve_default_category,
)

SCHEMA_VERSION = 7
_CATEGORY_CHECK_SQL = ",".join(f"'{k}'" for k in ALL_CATEGORY_KEYS)
_BUSY_TIMEOUT_MS = 500
_WAL_AUTOCHECKPOINT_PAGES = 256
_JOURNAL_SIZE_LIMIT_BYTES = 8 * 1024 * 1024
RETENTION_DAY_OPTIONS = (0, 30, 90, 180, 365)


def normalize_rule_match_text(match_text: str, match_kind: str) -> str:
    raw = match_text.strip().lower()
    if match_kind == "exact_basename":
        return os.path.basename(raw.replace("/", "\\"))
    return raw.replace("\\", "/")


def _overlap_ms(start_ts: float, end_ts: float, duration_ms: int, q_from: float, q_to: float) -> float:
    span = end_ts - start_ts
    if span <= 0 or duration_ms <= 0:
        return 0.0
    overlap = max(0.0, min(end_ts, q_to) - max(start_ts, q_from))
    if overlap <= 0:
        return 0.0
    return duration_ms * (overlap / span)


@dataclass(slots=True)
class AppStat:
    exe_name: str
    exe_path: str
    active_ms: float
    category: str = ""
    window_title: str | None = None


@dataclass(frozen=True, slots=True)
class BufferedInterval:
    kind: str
    start_ts: float
    end_ts: float
    duration_ms: int
    exe_path: str | None = None
    exe_name: str | None = None
    window_title: str | None = None
    row_id: int | None = None


@dataclass(frozen=True, slots=True)
class Persisted:
    pc_row_id: int | None
    app_row_id: int | None

    @property
    def pc_id(self) -> int | None:
        return self.pc_row_id

    @property
    def app_id(self) -> int | None:
        return self.app_row_id


@dataclass(slots=True)
class PeriodStats:
    q_from: float
    q_to: float
    pc_ms: float
    apps: list[AppStat]
    by_category: dict[str, float]
    chart_mode: str
    chart_series: list[tuple[str, float]]
    estimated_uptime_sec: float
    previous_pc_ms: float | None = None
    chart_by_category: dict[str, list[float]] = field(default_factory=dict)

    @property
    def app_ms(self) -> float:
        return sum(a.active_ms for a in self.apps)

    @property
    def coverage_pct(self) -> float:
        if self.pc_ms <= 0:
            return 0.0
        return min(100.0, 100.0 * self.app_ms / self.pc_ms)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._conn.row_factory = sqlite3.Row
        self._category_rules_cache: list[sqlite3.Row] | None = None
        try:
            self._init_schema()
        except Exception:
            self._conn.close()
            raise

    def close(self) -> None:
        try:
            self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except sqlite3.Error:
            pass
        finally:
            self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        conn = self._conn
        conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA secure_delete = ON")
        conn.execute(f"PRAGMA wal_autocheckpoint = {_WAL_AUTOCHECKPOINT_PAGES}")
        conn.execute(f"PRAGMA journal_size_limit = {_JOURNAL_SIZE_LIMIT_BYTES}")

        user_tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not user_tables:
            self._create_schema_v7()
        else:
            if "meta" not in user_tables:
                with self.transaction() as tx:
                    tx.execute(
                        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
                    )
                    self._set_schema_version(tx, 1)
            elif self._schema_version() is None:
                with self.transaction() as tx:
                    self._set_schema_version(tx, 1)
            self._apply_migrations()
        self.apply_retention_policy()

    def _create_schema_v7(self) -> None:
        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            conn.execute(
                """
                CREATE TABLE intervals (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  kind TEXT NOT NULL CHECK (kind IN ('pc_active', 'app')),
                  exe_path TEXT,
                  exe_name TEXT,
                  window_title TEXT,
                  start_ts REAL NOT NULL,
                  end_ts REAL NOT NULL,
                  duration_ms INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE boot_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  boot_ts REAL NOT NULL,
                  logged_at REAL NOT NULL,
                  last_seen_ts REAL NOT NULL
                )
                """
            )
            conn.execute(
                f"""
                CREATE TABLE app_category_rules (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  match_text TEXT NOT NULL,
                  match_kind TEXT NOT NULL CHECK (
                    match_kind IN ('exact_basename', 'path_contains')
                  ),
                  category TEXT NOT NULL CHECK (category IN ({_CATEGORY_CHECK_SQL})),
                  priority INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._create_final_indexes(conn)
            conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('collect_window_titles', '0')
                """
            )
            conn.execute(
                """
                INSERT INTO meta (key, value)
                VALUES ('retention_days', '0')
                """
            )
            self._set_schema_version(conn, SCHEMA_VERSION)

    def _create_final_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_intervals_kind_start "
            "ON intervals (kind, start_ts)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_app_cat_rules_prio "
            "ON app_category_rules (priority DESC, id DESC)"
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_app_cat_rules_normalized_unique
            ON app_category_rules (
              match_kind,
              lower(trim(replace(match_text, char(92), '/')))
            )
            """
        )

    def _schema_version(self) -> int | None:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
        conn.execute(
            """
            INSERT INTO meta (key, value) VALUES ('schema_version', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (str(version),),
        )

    # --- settings ---
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return row[0]

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self._conn.commit()

    def get_excluded_exes(self) -> frozenset[str]:
        raw = self.get_setting("excluded_exes", "[]") or "[]"
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return frozenset(str(x).lower() for x in data)
        except json.JSONDecodeError:
            pass
        return frozenset()

    def set_excluded_exes(self, names: set[str]) -> None:
        self.set_setting("excluded_exes", json.dumps(sorted(names)))

    def get_afk_seconds(self) -> float:
        raw = self.get_setting("afk_seconds")
        if raw is None:
            return 120.0
        try:
            return max(5.0, float(raw))
        except ValueError:
            return 120.0

    def set_afk_seconds(self, sec: float) -> None:
        self.set_setting("afk_seconds", str(max(5.0, sec)))

    def get_autostart_enabled(self) -> bool:
        return (self.get_setting("autostart_enabled", "0") or "0") == "1"

    def set_autostart_enabled(self, enabled: bool) -> None:
        self.set_setting("autostart_enabled", "1" if enabled else "0")

    def get_show_main_window_on_launch(self) -> bool:
        """Показывать главное окно при обычном запуске (не через --background / автозагрузку)."""
        return (self.get_setting("show_main_window_on_launch", "1") or "1") == "1"

    def set_show_main_window_on_launch(self, show: bool) -> None:
        self.set_setting("show_main_window_on_launch", "1" if show else "0")

    def get_collect_window_titles(self) -> bool:
        return (self.get_setting("collect_window_titles", "0") or "0") == "1"

    def set_collect_window_titles(self, enabled: bool) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                INSERT INTO meta (key, value) VALUES ('collect_window_titles', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("1" if enabled else "0",),
            )
            if not enabled:
                conn.execute(
                    "UPDATE intervals SET window_title = NULL "
                    "WHERE window_title IS NOT NULL"
                )
        if not enabled:
            self._compact_private_data()

    def get_retention_days(self) -> int:
        raw = self.get_setting("retention_days", "0") or "0"
        try:
            days = int(raw)
        except ValueError:
            return 0
        return days if days in RETENTION_DAY_OPTIONS else 0

    def set_retention_days(self, days: int) -> None:
        normalized = int(days)
        if normalized not in RETENTION_DAY_OPTIONS:
            raise ValueError(f"unsupported retention period: {days}")
        self.set_setting("retention_days", str(normalized))

    def apply_retention_policy(self, *, now: float | None = None) -> int:
        days = self.get_retention_days()
        if days <= 0:
            return 0
        cutoff = (time.time() if now is None else float(now)) - days * 86400.0
        with self.transaction() as conn:
            interval_count = conn.execute(
                "DELETE FROM intervals WHERE end_ts < ?", (cutoff,)
            ).rowcount
            boot_count = conn.execute(
                "DELETE FROM boot_log WHERE last_seen_ts < ?", (cutoff,)
            ).rowcount
        deleted = max(0, int(interval_count)) + max(0, int(boot_count))
        if deleted:
            self._compact_private_data()
        return deleted

    def delete_all_history(self) -> int:
        """Delete collected usage while preserving settings and category rules."""
        with self.transaction() as conn:
            interval_count = conn.execute("DELETE FROM intervals").rowcount
            boot_count = conn.execute("DELETE FROM boot_log").rowcount
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN ('intervals', 'boot_log')"
            )
        self._compact_private_data()
        return max(0, int(interval_count)) + max(0, int(boot_count))

    def _compact_private_data(self) -> None:
        """Remove deleted payloads from the main DB and the WAL."""
        self._conn.execute("PRAGMA secure_delete = ON")
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._conn.execute("VACUUM")
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # --- intervals ---
    def insert_interval(
        self,
        kind: str,
        *,
        exe_path: str | None,
        exe_name: str | None,
        window_title: str | None,
        start_ts: float,
        end_ts: float,
        duration_ms: int,
        commit: bool = True,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO intervals (kind, exe_path, exe_name, window_title, start_ts, end_ts, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (kind, exe_path, exe_name, window_title, start_ts, end_ts, duration_ms),
        )
        if commit:
            self._conn.commit()
        return int(cur.lastrowid)

    def update_interval(
        self, row_id: int, end_ts: float, duration_ms: int, *, commit: bool = True
    ) -> None:
        self._conn.execute(
            "UPDATE intervals SET end_ts = ?, duration_ms = ? WHERE id = ?",
            (end_ts, duration_ms, row_id),
        )
        if commit:
            self._conn.commit()

    def update_window_title(
        self, row_id: int, window_title: str, *, commit: bool = True
    ) -> None:
        self._conn.execute(
            "UPDATE intervals SET window_title = ? WHERE id = ?",
            (window_title, row_id),
        )
        if commit:
            self._conn.commit()

    def persist_usage(
        self,
        intervals: Sequence[BufferedInterval] | BufferedInterval | None = (),
        legacy_app: BufferedInterval | None = None,
    ) -> list[int] | Persisted:
        """Persist intervals atomically and return row IDs in input order.

        The two-interval form is retained for compatibility with 1.2 callers. New
        code must pass one sequence and receives ``list[int]``.
        """
        legacy_call = isinstance(intervals, BufferedInterval) or legacy_app is not None
        if legacy_call:
            pc = intervals if isinstance(intervals, BufferedInterval) else None
            if pc is not None and pc.kind != "pc_active":
                raise ValueError(f"expected 'pc_active' interval, got {pc.kind!r}")
            if legacy_app is not None and legacy_app.kind != "app":
                raise ValueError(f"expected 'app' interval, got {legacy_app.kind!r}")
            batch = [item for item in (pc, legacy_app) if item is not None]
        else:
            batch = list(intervals or ())

        for interval in batch:
            if not isinstance(interval, BufferedInterval):
                raise TypeError("persist_usage accepts BufferedInterval values")
            if interval.kind not in ("pc_active", "app"):
                raise ValueError(f"unsupported interval kind: {interval.kind!r}")
            if interval.duration_ms <= 0 or interval.end_ts <= interval.start_ts:
                raise ValueError("interval must have positive duration and wall-clock span")

        row_ids: list[int] = []
        if batch:
            with self.transaction() as conn:
                for interval in batch:
                    if interval.row_id is None:
                        cur = conn.execute(
                            """
                            INSERT INTO intervals (
                              kind, exe_path, exe_name, window_title,
                              start_ts, end_ts, duration_ms
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                interval.kind,
                                interval.exe_path,
                                interval.exe_name,
                                interval.window_title,
                                interval.start_ts,
                                interval.end_ts,
                                interval.duration_ms,
                            ),
                        )
                        row_ids.append(int(cur.lastrowid))
                        continue

                    cur = conn.execute(
                        """
                        UPDATE intervals
                        SET end_ts = ?, duration_ms = ?, window_title = ?
                        WHERE id = ? AND kind = ?
                        """,
                        (
                            interval.end_ts,
                            interval.duration_ms,
                            interval.window_title,
                            interval.row_id,
                            interval.kind,
                        ),
                    )
                    if cur.rowcount != 1:
                        raise LookupError(
                            f"interval row {interval.row_id} no longer exists"
                        )
                    row_ids.append(interval.row_id)

        if legacy_call:
            id_iter = iter(row_ids)
            return Persisted(
                pc_row_id=next(id_iter) if isinstance(intervals, BufferedInterval) else None,
                app_row_id=next(id_iter) if legacy_app is not None else None,
            )
        return row_ids

    def log_boot_if_new(self, boot_ts: float, seen_ts: float | None = None) -> int:
        seen = time.time() if seen_ts is None else float(seen_ts)
        with self.transaction() as conn:
            last = conn.execute(
                "SELECT id, boot_ts FROM boot_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if last is not None and abs(float(last["boot_ts"]) - boot_ts) <= 60:
                row_id = int(last["id"])
                conn.execute(
                    """
                    UPDATE boot_log
                    SET last_seen_ts = max(
                      coalesce(last_seen_ts, logged_at, boot_ts), ?
                    )
                    WHERE id = ?
                    """,
                    (seen, row_id),
                )
                return row_id
            cur = conn.execute(
                """
                INSERT INTO boot_log (boot_ts, logged_at, last_seen_ts)
                VALUES (?, ?, ?)
                """,
                (boot_ts, seen, seen),
            )
            return int(cur.lastrowid)

    def touch_boot(self, boot_ts: float, seen_ts: float | None = None) -> bool:
        seen = time.time() if seen_ts is None else float(seen_ts)
        with self.transaction() as conn:
            row = conn.execute(
                """
                SELECT id FROM boot_log
                WHERE abs(boot_ts - ?) <= 60
                ORDER BY id DESC LIMIT 1
                """,
                (boot_ts,),
            ).fetchone()
            if row is None:
                return False
            conn.execute(
                """
                UPDATE boot_log
                SET last_seen_ts = max(
                  coalesce(last_seen_ts, logged_at, boot_ts), ?
                )
                WHERE id = ?
                """,
                (seen, int(row["id"])),
            )
            return True

    def total_pc_ms(self, q_from: float, q_to: float) -> float:
        total = 0.0
        for row in self._conn.execute(
            """
            SELECT start_ts, end_ts, duration_ms
            FROM intervals
            WHERE kind = 'pc_active'
              AND start_ts < ?
              AND end_ts > ?
              AND end_ts > start_ts
              AND duration_ms > 0
            """,
            (q_to, q_from),
        ):
            total += _overlap_ms(
                float(row["start_ts"]),
                float(row["end_ts"]),
                int(row["duration_ms"]),
                q_from,
                q_to,
            )
        return total

    def estimated_pc_uptime_seconds(self, q_from: float, q_to: float) -> float:
        """Estimate uptime without counting offline gaps between recorded boots."""
        rows = self._conn.execute(
            """
            SELECT boot_ts, logged_at, last_seen_ts
            FROM boot_log ORDER BY boot_ts ASC, id ASC
            """
        ).fetchall()
        if not rows:
            return 0.0
        now = time.time()
        total = 0.0
        for index, row in enumerate(rows):
            start = float(row["boot_ts"])
            recorded_end = max(
                start,
                float(row["last_seen_ts"] or row["logged_at"] or start),
            )
            if index == len(rows) - 1:
                end = max(recorded_end, now)
            else:
                end = min(recorded_end, float(rows[index + 1]["boot_ts"]))
            total += max(0.0, min(end, q_to) - max(start, q_from))
        return total

    def totals_by_app(self, q_from: float, q_to: float) -> list[AppStat]:
        """Суммарное время по приложению: одна строка на exe (окно в фокусе)."""
        acc: dict[tuple[str, str], float] = {}
        for row in self._conn.execute(
            """
            SELECT exe_path, exe_name, start_ts, end_ts, duration_ms
            FROM intervals
            WHERE kind = 'app'
              AND start_ts < ?
              AND end_ts > ?
              AND end_ts > start_ts
              AND duration_ms > 0
            """,
            (q_to, q_from),
        ):
            path = row["exe_path"] or ""
            name = row["exe_name"] or ""
            key = (path, name)
            ms = _overlap_ms(
                float(row["start_ts"]),
                float(row["end_ts"]),
                int(row["duration_ms"]),
                q_from,
                q_to,
            )
            acc[key] = acc.get(key, 0.0) + ms
        out = []
        for (path, name), v in acc.items():
            if v > 0.5:
                out.append(
                    AppStat(
                        exe_name=name,
                        exe_path=path,
                        active_ms=v,
                        category=self.resolve_category(path),
                    )
                )
        out.sort(key=lambda x: x.active_ms, reverse=True)
        return out

    def earliest_interval_start(self) -> float | None:
        """Minimum start_ts across all intervals, or None if the table is empty."""
        row = self._conn.execute("SELECT MIN(start_ts) FROM intervals").fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    def boot_time_sum_logged(self) -> float | None:
        """Sum the recorded extent of each boot session."""
        rows = self._conn.execute(
            "SELECT boot_ts, logged_at, last_seen_ts FROM boot_log"
        ).fetchall()
        if not rows:
            return None
        return sum(
            max(
                0.0,
                float(r["last_seen_ts"] or r["logged_at"]) - float(r["boot_ts"]),
            )
            for r in rows
        )

    def _apply_migrations(self) -> None:
        ver = self._schema_version() or 1
        if ver < 2:
            with self.transaction() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_category_rules (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      match_text TEXT NOT NULL,
                      match_kind TEXT NOT NULL CHECK (
                        match_kind IN ('exact_basename', 'path_contains')
                      ),
                      category TEXT NOT NULL CHECK (
                        category IN ('productive', 'unproductive', 'neutral')
                      ),
                      priority INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_app_cat_rules_prio "
                    "ON app_category_rules (priority DESC, id DESC)"
                )
                self._set_schema_version(conn, 2)
            ver = 2
        if ver < 3:
            with self.transaction() as conn:
                conn.execute("DROP TABLE IF EXISTS app_category_rules_new")
                conn.execute(
                    """
                    CREATE TABLE app_category_rules_new (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      match_text TEXT NOT NULL,
                      match_kind TEXT NOT NULL CHECK (
                        match_kind IN ('exact_basename', 'path_contains')
                      ),
                      category TEXT NOT NULL CHECK (category IN (
                        'work','distraction','communication','games',
                        'media','devtools','system','other'
                      )),
                      priority INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO app_category_rules_new (
                      id, match_text, match_kind, category, priority
                    )
                    SELECT id, match_text, match_kind,
                      CASE category
                        WHEN 'productive' THEN 'work'
                        WHEN 'unproductive' THEN 'distraction'
                        WHEN 'neutral' THEN 'other'
                        ELSE category
                      END,
                      priority
                    FROM app_category_rules
                    """
                )
                conn.execute("DROP TABLE app_category_rules")
                conn.execute(
                    "ALTER TABLE app_category_rules_new "
                    "RENAME TO app_category_rules"
                )
                conn.execute(
                    "CREATE INDEX idx_app_cat_rules_prio "
                    "ON app_category_rules (priority DESC, id DESC)"
                )
                self._set_schema_version(conn, 3)
            ver = 3
        if ver < 4:
            with self.transaction() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO meta (key, value)
                    VALUES ('show_main_window_on_launch', '1')
                    """
                )
                self._set_schema_version(conn, 4)
            ver = 4
        if ver < 5:
            with self.transaction() as conn:
                conn.execute("DROP TABLE IF EXISTS app_category_rules_new")
                conn.execute(
                    f"""
                    CREATE TABLE app_category_rules_new (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      match_text TEXT NOT NULL,
                      match_kind TEXT NOT NULL CHECK (
                        match_kind IN ('exact_basename', 'path_contains')
                      ),
                      category TEXT NOT NULL CHECK (
                        category IN ({_CATEGORY_CHECK_SQL})
                      ),
                      priority INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO app_category_rules_new (
                      id, match_text, match_kind, category, priority
                    )
                    SELECT id, match_text, match_kind,
                      CASE category
                        WHEN 'productive' THEN 'work'
                        WHEN 'unproductive' THEN 'distraction'
                        WHEN 'neutral' THEN 'other'
                        ELSE category
                      END,
                      priority
                    FROM app_category_rules
                    """
                )
                conn.execute("DROP TABLE app_category_rules")
                conn.execute(
                    "ALTER TABLE app_category_rules_new "
                    "RENAME TO app_category_rules"
                )
                conn.execute(
                    "CREATE INDEX idx_app_cat_rules_prio "
                    "ON app_category_rules (priority DESC, id DESC)"
                )
                conn.execute(
                    """
                    INSERT OR IGNORE INTO meta (key, value)
                    VALUES ('autostart_enabled', '0')
                    """
                )
                self._set_schema_version(conn, 5)
            ver = 5
        if ver < 6:
            self._migrate_v5_to_v6()
            ver = 6
        if ver < 7:
            self._migrate_v6_to_v7()

    def _migrate_v5_to_v6(self) -> None:
        with self.transaction() as conn:
            conn.execute("DROP INDEX IF EXISTS idx_intervals_kind_time")
            conn.execute("DROP INDEX IF EXISTS idx_intervals_pc_overlap")
            conn.execute("DROP INDEX IF EXISTS idx_intervals_app_overlap")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_intervals_kind_start "
                "ON intervals (kind, start_ts)"
            )
            self._set_schema_version(conn, 6)

    def _migrate_v6_to_v7(self) -> None:
        with self.transaction() as conn:
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(boot_log)")
            }
            if "last_seen_ts" not in columns:
                conn.execute("ALTER TABLE boot_log ADD COLUMN last_seen_ts REAL")
            conn.execute(
                """
                UPDATE boot_log
                SET last_seen_ts = max(
                  boot_ts,
                  coalesce(last_seen_ts, logged_at, boot_ts)
                )
                """
            )
            conn.execute(
                "UPDATE intervals SET window_title = NULL "
                "WHERE window_title IS NOT NULL"
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO meta (key, value)
                VALUES ('collect_window_titles', '0')
                """
            )

            rows = conn.execute(
                """
                SELECT id, match_text, match_kind, category, priority
                FROM app_category_rules
                ORDER BY priority DESC, id DESC
                """
            ).fetchall()
            seen: set[tuple[str, str]] = set()
            for row in rows:
                rule_id = int(row["id"])
                match_kind = str(row["match_kind"] or "").strip().lower()
                match_text = self._normalize_match_text(
                    str(row["match_text"] or ""), match_kind
                )
                key = (match_kind, match_text.replace("\\", "/").strip().lower())
                if key in seen:
                    conn.execute(
                        "DELETE FROM app_category_rules WHERE id = ?", (rule_id,)
                    )
                    continue
                seen.add(key)
                conn.execute(
                    """
                    UPDATE app_category_rules
                    SET match_text = ?, match_kind = ?, category = ?
                    WHERE id = ?
                    """,
                    (
                        match_text,
                        match_kind,
                        normalize_legacy_category(str(row["category"])),
                        rule_id,
                    ),
                )
            conn.execute("DROP INDEX IF EXISTS idx_app_cat_rules_normalized_unique")
            conn.execute(
                """
                CREATE UNIQUE INDEX idx_app_cat_rules_normalized_unique
                ON app_category_rules (
                  match_kind,
                  lower(trim(replace(match_text, char(92), '/')))
                )
                """
            )
            self._set_schema_version(conn, 7)

    # --- app categories ---
    def _invalidate_category_rules(self) -> None:
        self._category_rules_cache = None

    def _category_rules(self) -> list[sqlite3.Row]:
        if self._category_rules_cache is None:
            self._category_rules_cache = list(
                self._conn.execute(
                    """
                    SELECT id, match_text, match_kind, category, priority
                    FROM app_category_rules
                    ORDER BY priority DESC, id DESC
                    """
                ).fetchall()
            )
        return self._category_rules_cache

    def _normalize_match_text(self, match_text: str, match_kind: str) -> str:
        return normalize_rule_match_text(match_text, match_kind)

    def list_category_rules(self) -> list[sqlite3.Row]:
        return list(self._category_rules())

    def add_category_rule(
        self,
        match_text: str,
        match_kind: str,
        category: str,
        priority: int | None = None,
    ) -> int:
        norm_match = self._normalize_match_text(match_text, match_kind)
        if priority is None:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(priority), 0) + 10 FROM app_category_rules"
            ).fetchone()
            priority = int(row[0]) if row else 10
        with self.transaction() as conn:
            cur = conn.execute(
                """
                INSERT INTO app_category_rules (
                  match_text, match_kind, category, priority
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    norm_match,
                    match_kind,
                    normalize_legacy_category(category),
                    priority,
                ),
            )
        self._invalidate_category_rules()
        return int(cur.lastrowid)

    def update_category_rule(
        self, rule_id: int, match_text: str, match_kind: str, category: str
    ) -> None:
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE app_category_rules
                SET match_text = ?, match_kind = ?, category = ?
                WHERE id = ?
                """,
                (
                    self._normalize_match_text(match_text, match_kind),
                    match_kind,
                    normalize_legacy_category(category),
                    rule_id,
                ),
            )
        self._invalidate_category_rules()

    def delete_category_rule(self, rule_id: int) -> None:
        self._conn.execute("DELETE FROM app_category_rules WHERE id = ?", (rule_id,))
        self._conn.commit()
        self._invalidate_category_rules()

    def move_category_rule(self, rule_id: int, direction: int) -> None:
        rows = self.list_category_rules()
        idx = next((i for i, r in enumerate(rows) if int(r["id"]) == rule_id), -1)
        if idx < 0:
            return
        target = idx - 1 if direction < 0 else idx + 1
        if target < 0 or target >= len(rows):
            return
        ordered_ids = [int(r["id"]) for r in rows]
        ordered_ids[idx], ordered_ids[target] = ordered_ids[target], ordered_ids[idx]
        with self.transaction() as conn:
            total = len(ordered_ids)
            for i, rid in enumerate(ordered_ids):
                conn.execute(
                    "UPDATE app_category_rules SET priority = ? WHERE id = ?",
                    ((total - i) * 10, rid),
                )
        self._invalidate_category_rules()

    def resolve_category(self, exe_path: str) -> str:
        path_lower = exe_path.lower().replace("\\", "/")
        base = path_lower.rsplit("/", 1)[-1]
        for r in self._category_rules():
            mt = self._normalize_match_text(
                str(r["match_text"] or ""), str(r["match_kind"] or "")
            )
            if not mt:
                continue
            if r["match_kind"] == "exact_basename" and base == mt:
                return normalize_legacy_category(str(r["category"]))
            if r["match_kind"] == "path_contains" and mt in path_lower:
                return normalize_legacy_category(str(r["category"]))
        return resolve_default_category(exe_path)

    def totals_by_category(self, q_from: float, q_to: float) -> dict[str, float]:
        acc = {k: 0.0 for k in ALL_CATEGORY_KEYS}
        for a in self.totals_by_app(q_from, q_to):
            cat = a.category or self.resolve_category(a.exe_path)
            if cat not in acc:
                acc[cat] = 0.0
            acc[cat] += a.active_ms
        return acc

    @staticmethod
    def _calendar_day_slots(
        q_from: float, q_to: float
    ) -> list[tuple[str, float, float]]:
        if q_to <= q_from:
            return []
        tz = datetime.now().astimezone().tzinfo
        d0 = datetime.fromtimestamp(q_from, tz=tz).date()
        d1 = datetime.fromtimestamp(max(q_from, q_to - 0.001), tz=tz).date()
        slots: list[tuple[str, float, float]] = []
        day = d0
        while day <= d1:
            day_start = datetime.combine(day, dt_time(0, 0), tzinfo=tz)
            day_end = day_start + timedelta(days=1)
            slots.append(
                (
                    day.isoformat(),
                    max(q_from, day_start.timestamp()),
                    min(q_to, day_end.timestamp()),
                )
            )
            day += timedelta(days=1)
        return slots

    @staticmethod
    def _hour_slots(q_from: float, q_to: float) -> list[tuple[str, float, float]]:
        if q_to <= q_from:
            return []
        tz = datetime.now().astimezone().tzinfo
        slots: list[tuple[str, float, float]] = []
        current = q_from
        while current < q_to:
            hour = datetime.fromtimestamp(current, tz=tz).replace(
                minute=0, second=0, microsecond=0
            )
            slot_start = hour.timestamp()
            slot_end = slot_start + 3600.0
            slots.append(
                (
                    hour.strftime("%Y-%m-%d %H:00"),
                    max(q_from, slot_start),
                    min(q_to, slot_end),
                )
            )
            current = slot_end
        return slots

    @staticmethod
    def _calendar_month_slots(
        q_from: float, q_to: float
    ) -> list[tuple[str, float, float]]:
        if q_to <= q_from:
            return []
        tz = datetime.now().astimezone().tzinfo
        current = datetime.fromtimestamp(q_from, tz=tz).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        last = datetime.fromtimestamp(max(q_from, q_to - 0.001), tz=tz)
        slots: list[tuple[str, float, float]] = []
        while current <= last:
            if current.month == 12:
                following = current.replace(year=current.year + 1, month=1)
            else:
                following = current.replace(month=current.month + 1)
            slots.append(
                (
                    current.strftime("%Y-%m"),
                    max(q_from, current.timestamp()),
                    min(q_to, following.timestamp()),
                )
            )
            current = following
        return slots

    @classmethod
    def _chart_slots(
        cls,
        q_from: float,
        q_to: float,
        period: str | None = None,
    ) -> tuple[str, list[tuple[str, float, float]]]:
        slot_to = q_to
        if period in ("today", "week", "month", "year"):
            tz = datetime.now().astimezone().tzinfo
            start = datetime.fromtimestamp(q_from, tz=tz)
            if period == "today":
                slot_to = max(q_to, (start + timedelta(days=1)).timestamp())
                return "hour", cls._hour_slots(q_from, slot_to)
            if period == "week":
                slot_to = max(q_to, (start + timedelta(days=7)).timestamp())
                return "day", cls._calendar_day_slots(q_from, slot_to)
            if period == "month":
                if start.month == 12:
                    following = start.replace(year=start.year + 1, month=1, day=1)
                else:
                    following = start.replace(month=start.month + 1, day=1)
                slot_to = max(q_to, following.timestamp())
                return "day", cls._calendar_day_slots(q_from, slot_to)
            following = start.replace(year=start.year + 1, month=1, day=1)
            slot_to = max(q_to, following.timestamp())
            return "month", cls._calendar_month_slots(q_from, slot_to)

        span = q_to - q_from
        if span <= 0:
            return "day", []
        if span <= 2.5 * 86400:
            return "hour", cls._hour_slots(q_from, q_to)
        if span <= 62 * 86400:
            return "day", cls._calendar_day_slots(q_from, q_to)
        return "month", cls._calendar_month_slots(q_from, q_to)

    def bucket_pc_active_by_calendar_day(self, q_from: float, q_to: float) -> list[tuple[str, float]]:
        """List of (YYYY-MM-DD, active_ms) for each calendar day overlapping the range."""
        slots = self._calendar_day_slots(q_from, q_to)
        return self._bucket_pc_active(slots, q_from, q_to)

    def bucket_pc_active_by_hour_slots(
        self, q_from: float, q_to: float
    ) -> list[tuple[str, float]]:
        """Each local calendar hour in range: label 'dd HH:00' or 'YYYY-mm-dd HH:00', ms."""
        slots = self._hour_slots(q_from, q_to)
        return self._bucket_pc_active(slots, q_from, q_to)

    def bucket_pc_active_by_calendar_month(
        self, q_from: float, q_to: float
    ) -> list[tuple[str, float]]:
        slots = self._calendar_month_slots(q_from, q_to)
        return self._bucket_pc_active(slots, q_from, q_to)

    def _bucket_pc_active(
        self, slots: list[tuple[str, float, float]], q_from: float, q_to: float
    ) -> list[tuple[str, float]]:
        totals = [0.0 for _ in slots]
        rows = self._conn.execute(
            """
            SELECT start_ts, end_ts, duration_ms
            FROM intervals
            WHERE kind = 'pc_active'
              AND start_ts < ?
              AND end_ts > ?
              AND end_ts > start_ts
              AND duration_ms > 0
            ORDER BY start_ts
            """,
            (q_to, q_from),
        )
        slot_i = 0
        for row in rows:
            start = float(row["start_ts"])
            end = float(row["end_ts"])
            duration = int(row["duration_ms"])
            while slot_i < len(slots) and slots[slot_i][2] <= start:
                slot_i += 1
            i = slot_i
            while i < len(slots) and slots[i][1] < end:
                _label, slot_start, slot_end = slots[i]
                if slot_end > slot_start:
                    totals[i] += _overlap_ms(
                        start, end, duration, slot_start, slot_end
                    )
                i += 1
        return [(label, totals[i]) for i, (label, _a, _b) in enumerate(slots)]

    def chart_pc_active_series(
        self, q_from: float, q_to: float
    ) -> tuple[str, list[tuple[str, float]]]:
        """Returns chart mode and active PC time for calendar-aligned slots."""
        mode, slots = self._chart_slots(q_from, q_to)
        return mode, self._bucket_pc_active(slots, q_from, q_to)

    def _bucket_app_categories(
        self,
        slots: list[tuple[str, float, float]],
        q_from: float,
        q_to: float,
    ) -> dict[str, list[float]]:
        totals = {category: [0.0 for _ in slots] for category in ALL_CATEGORY_KEYS}
        rows = self._conn.execute(
            """
            SELECT start_ts, end_ts, duration_ms, exe_path, exe_name
            FROM intervals
            WHERE kind = 'app'
              AND start_ts < ?
              AND end_ts > ?
              AND end_ts > start_ts
              AND duration_ms > 0
            ORDER BY start_ts
            """,
            (q_to, q_from),
        )
        category_cache: dict[str, str] = {}
        slot_i = 0
        for row in rows:
            start = float(row["start_ts"])
            end = float(row["end_ts"])
            duration = int(row["duration_ms"])
            path = str(row["exe_path"] or row["exe_name"] or "")
            category = category_cache.get(path)
            if category is None:
                category = self.resolve_category(path)
                category_cache[path] = category
            values = totals.setdefault(category, [0.0 for _ in slots])
            while slot_i < len(slots) and slots[slot_i][2] <= start:
                slot_i += 1
            index = slot_i
            while index < len(slots) and slots[index][1] < end:
                _label, slot_start, slot_end = slots[index]
                if slot_end > slot_start:
                    values[index] += _overlap_ms(
                        start, end, duration, slot_start, slot_end
                    )
                index += 1
        return totals

    def period_stats(
        self,
        q_from: float,
        q_to: float,
        previous_range: tuple[float, float] | None = None,
        *,
        include_chart: bool = True,
        chart_period: str | None = None,
    ) -> PeriodStats:
        pc_ms = self.total_pc_ms(q_from, q_to)
        previous_pc_ms: float | None = None
        if previous_range is not None:
            previous_from, previous_to = previous_range
            if previous_to > previous_from:
                previous_pc_ms = self.total_pc_ms(previous_from, previous_to)
        apps = self.totals_by_app(q_from, q_to)
        by_category = {k: 0.0 for k in ALL_CATEGORY_KEYS}
        for app in apps:
            cat = app.category or self.resolve_category(app.exe_path)
            by_category[cat] = by_category.get(cat, 0.0) + app.active_ms
        chart_mode = ""
        chart_series: list[tuple[str, float]] = []
        chart_by_category: dict[str, list[float]] = {}
        if include_chart:
            chart_mode, chart_slots = self._chart_slots(
                q_from, q_to, chart_period
            )
            chart_series = self._bucket_pc_active(chart_slots, q_from, q_to)
            chart_by_category = self._bucket_app_categories(chart_slots, q_from, q_to)
        return PeriodStats(
            q_from=q_from,
            q_to=q_to,
            pc_ms=pc_ms,
            apps=apps,
            by_category=by_category,
            chart_mode=chart_mode,
            chart_series=chart_series,
            estimated_uptime_sec=self.estimated_pc_uptime_seconds(q_from, q_to),
            previous_pc_ms=previous_pc_ms,
            chart_by_category=chart_by_category,
        )

    def optimize(self) -> None:
        self._conn.execute("PRAGMA optimize")
