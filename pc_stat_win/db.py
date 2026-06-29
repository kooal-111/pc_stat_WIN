from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

from pc_stat_win.categories import (
    ALL_CATEGORY_KEYS,
    normalize_legacy_category,
    resolve_default_category,
)

SCHEMA_VERSION = 5
_CATEGORY_CHECK_SQL = ",".join(f"'{k}'" for k in ALL_CATEGORY_KEYS)


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
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._category_rules_cache: list[sqlite3.Row] | None = None
        self._init_schema()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self._conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_schema(self) -> None:
        self._conn.executescript(
            f"""
            PRAGMA busy_timeout = 5000;
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS intervals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              kind TEXT NOT NULL CHECK (kind IN ('pc_active', 'app')),
              exe_path TEXT,
              exe_name TEXT,
              window_title TEXT,
              start_ts REAL NOT NULL,
              end_ts REAL NOT NULL,
              duration_ms INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_intervals_kind_time ON intervals (kind, start_ts, end_ts);
            CREATE INDEX IF NOT EXISTS idx_intervals_pc_overlap
              ON intervals (start_ts, end_ts, duration_ms)
              WHERE kind = 'pc_active';
            CREATE INDEX IF NOT EXISTS idx_intervals_app_overlap
              ON intervals (start_ts, end_ts, exe_path, exe_name, duration_ms)
              WHERE kind = 'app';

            CREATE TABLE IF NOT EXISTS boot_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              boot_ts REAL NOT NULL,
              logged_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_category_rules (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              match_text TEXT NOT NULL,
              match_kind TEXT NOT NULL CHECK (match_kind IN ('exact_basename', 'path_contains')),
              category TEXT NOT NULL CHECK (category IN ({_CATEGORY_CHECK_SQL})),
              priority INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_app_cat_rules_prio
              ON app_category_rules (priority DESC, id DESC);
            """
        )
        row = self._conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES ('schema_version', ?)",
                ("1",),
            )
        self._conn.commit()
        self._apply_migrations()

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

    def log_boot_if_new(self, boot_ts: float) -> None:
        last = self._conn.execute(
            "SELECT boot_ts FROM boot_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if last is None or abs(float(last[0]) - boot_ts) > 60:
            self._conn.execute(
                "INSERT INTO boot_log (boot_ts, logged_at) VALUES (?, ?)",
                (boot_ts, time.time()),
            )
            self._conn.commit()

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
        """Сумма длин пересечений сессий [boot_i, boot_{i+1}) с [q_from, q_to]; последняя сессия до now."""
        rows = self._conn.execute("SELECT boot_ts FROM boot_log ORDER BY boot_ts ASC").fetchall()
        if not rows:
            return max(0.0, q_to - q_from)
        boots = [float(r[0]) for r in rows]
        now = time.time()
        total = 0.0
        for i, start in enumerate(boots):
            end = boots[i + 1] if i + 1 < len(boots) else now
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
        """Sum of (logged_at - boot_ts) per boot session row — rough 'time machine was on while tracker ran'."""
        rows = self._conn.execute("SELECT boot_ts, logged_at FROM boot_log").fetchall()
        if not rows:
            return None
        return sum(max(0.0, float(r["logged_at"]) - float(r["boot_ts"])) for r in rows)

    def _apply_migrations(self) -> None:
        raw = self.get_setting("schema_version", "1")
        try:
            ver = int(raw or "1")
        except ValueError:
            ver = 1
        if ver < 2:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_category_rules (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  match_text TEXT NOT NULL,
                  match_kind TEXT NOT NULL CHECK (match_kind IN ('exact_basename', 'path_contains')),
                  category TEXT NOT NULL CHECK (category IN ('productive', 'unproductive', 'neutral')),
                  priority INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_app_cat_rules_prio ON app_category_rules (priority DESC, id DESC);
                """
            )
            self.set_setting("schema_version", "2")
            ver = 2
        if ver < 3:
            self._conn.executescript(
                """
                CREATE TABLE app_category_rules_new (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  match_text TEXT NOT NULL,
                  match_kind TEXT NOT NULL CHECK (match_kind IN ('exact_basename', 'path_contains')),
                  category TEXT NOT NULL CHECK (category IN (
                    'work','distraction','communication','games','media','devtools','system','other'
                  )),
                  priority INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO app_category_rules_new (id, match_text, match_kind, category, priority)
                SELECT id, match_text, match_kind,
                  CASE category
                    WHEN 'productive' THEN 'work'
                    WHEN 'unproductive' THEN 'distraction'
                    WHEN 'neutral' THEN 'other'
                    ELSE category
                  END,
                  priority
                FROM app_category_rules;
                DROP TABLE app_category_rules;
                ALTER TABLE app_category_rules_new RENAME TO app_category_rules;
                CREATE INDEX IF NOT EXISTS idx_app_cat_rules_prio ON app_category_rules (priority DESC, id DESC);
                """
            )
            self.set_setting("schema_version", "3")
            ver = 3
        if ver < 4:
            if self.get_setting("show_main_window_on_launch") is None:
                self.set_setting("show_main_window_on_launch", "1")
            self.set_setting("schema_version", "4")
            ver = 4
        if ver < 5:
            self._conn.executescript(
                f"""
                CREATE TABLE app_category_rules_new (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  match_text TEXT NOT NULL,
                  match_kind TEXT NOT NULL CHECK (match_kind IN ('exact_basename', 'path_contains')),
                  category TEXT NOT NULL CHECK (category IN ({_CATEGORY_CHECK_SQL})),
                  priority INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO app_category_rules_new (id, match_text, match_kind, category, priority)
                SELECT id, match_text, match_kind,
                  CASE category
                    WHEN 'productive' THEN 'work'
                    WHEN 'unproductive' THEN 'distraction'
                    WHEN 'neutral' THEN 'other'
                    ELSE category
                  END,
                  priority
                FROM app_category_rules;
                DROP TABLE app_category_rules;
                ALTER TABLE app_category_rules_new RENAME TO app_category_rules;
                CREATE INDEX IF NOT EXISTS idx_app_cat_rules_prio
                  ON app_category_rules (priority DESC, id DESC);
                """
            )
            if self.get_setting("autostart_enabled") is None:
                self.set_setting("autostart_enabled", "0")
            self.set_setting("schema_version", "5")
            ver = 5

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
        raw = match_text.strip().lower()
        if match_kind == "exact_basename":
            return os.path.basename(raw.replace("/", "\\"))
        return raw.replace("\\", "/")

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
        cur = self._conn.execute(
            """
            INSERT INTO app_category_rules (match_text, match_kind, category, priority)
            VALUES (?, ?, ?, ?)
            """,
            (norm_match, match_kind, normalize_legacy_category(category), priority),
        )
        self._conn.commit()
        self._invalidate_category_rules()
        return int(cur.lastrowid)

    def update_category_rule(
        self, rule_id: int, match_text: str, match_kind: str, category: str
    ) -> None:
        self._conn.execute(
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
        self._conn.commit()
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

    def bucket_pc_active_by_calendar_day(self, q_from: float, q_to: float) -> list[tuple[str, float]]:
        """List of (YYYY-MM-DD, active_ms) for each calendar day overlapping the range."""
        tz = datetime.now().astimezone().tzinfo
        d0 = datetime.fromtimestamp(q_from, tz=tz).date()
        d1 = datetime.fromtimestamp(q_to, tz=tz).date()
        slots: list[tuple[str, float, float]] = []
        d = d0
        while d <= d1:
            day_start = datetime.combine(d, dt_time(0, 0), tzinfo=tz)
            day_end = day_start + timedelta(days=1)
            ts0 = day_start.timestamp()
            ts1 = day_end.timestamp()
            slots.append((d.isoformat(), max(q_from, ts0), min(q_to, ts1)))
            d += timedelta(days=1)
        return self._bucket_pc_active(slots, q_from, q_to)

    def bucket_pc_active_by_hour_slots(
        self, q_from: float, q_to: float
    ) -> list[tuple[str, float]]:
        """Each local calendar hour in range: label 'dd HH:00' or 'YYYY-mm-dd HH:00', ms."""
        tz = datetime.now().astimezone().tzinfo
        slots: list[tuple[str, float, float]] = []
        t = q_from
        while t < q_to:
            dt = datetime.fromtimestamp(t, tz=tz)
            hs = dt.replace(minute=0, second=0, microsecond=0)
            t0 = hs.timestamp()
            t1 = t0 + 3600.0
            label = hs.strftime("%m-%d %H:00")
            slots.append((label, max(q_from, t0), min(q_to, t1)))
            t = t1
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
            """,
            (q_to, q_from),
        ).fetchall()
        for row in rows:
            start = float(row["start_ts"])
            end = float(row["end_ts"])
            duration = int(row["duration_ms"])
            for i, (_label, slot_start, slot_end) in enumerate(slots):
                if slot_end > slot_start:
                    totals[i] += _overlap_ms(start, end, duration, slot_start, slot_end)
        return [(label, totals[i]) for i, (label, _a, _b) in enumerate(slots)]

    def chart_pc_active_series(
        self, q_from: float, q_to: float
    ) -> tuple[str, list[tuple[str, float]]]:
        """Returns ('day'|'hour', list of (label, ms)) for charts."""
        span = q_to - q_from
        if span <= 0:
            return "day", []
        if span <= 2.5 * 86400:
            return "hour", self.bucket_pc_active_by_hour_slots(q_from, q_to)
        return "day", self.bucket_pc_active_by_calendar_day(q_from, q_to)

    def period_stats(self, q_from: float, q_to: float) -> PeriodStats:
        pc_ms = self.total_pc_ms(q_from, q_to)
        apps = self.totals_by_app(q_from, q_to)
        by_category = {k: 0.0 for k in ALL_CATEGORY_KEYS}
        for app in apps:
            cat = app.category or self.resolve_category(app.exe_path)
            by_category[cat] = by_category.get(cat, 0.0) + app.active_ms
        chart_mode, chart_series = self.chart_pc_active_series(q_from, q_to)
        return PeriodStats(
            q_from=q_from,
            q_to=q_to,
            pc_ms=pc_ms,
            apps=apps,
            by_category=by_category,
            chart_mode=chart_mode,
            chart_series=chart_series,
            estimated_uptime_sec=self.estimated_pc_uptime_seconds(q_from, q_to),
        )

    def optimize(self) -> None:
        self._conn.execute("PRAGMA optimize")
