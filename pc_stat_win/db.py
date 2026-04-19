from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from pc_stat_win.categories import (
    NEUTRAL,
    PRODUCTIVE,
    UNPRODUCTIVE,
    default_category_for_basename,
)


SCHEMA_VERSION = 2


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


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
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
            """
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

            CREATE TABLE IF NOT EXISTS boot_log (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              boot_ts REAL NOT NULL,
              logged_at REAL NOT NULL
            );
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
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO intervals (kind, exe_path, exe_name, window_title, start_ts, end_ts, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (kind, exe_path, exe_name, window_title, start_ts, end_ts, duration_ms),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def update_interval(self, row_id: int, end_ts: float, duration_ms: int) -> None:
        self._conn.execute(
            "UPDATE intervals SET end_ts = ?, duration_ms = ? WHERE id = ?",
            (end_ts, duration_ms, row_id),
        )
        self._conn.commit()

    def update_window_title(self, row_id: int, window_title: str) -> None:
        self._conn.execute(
            "UPDATE intervals SET window_title = ? WHERE id = ?",
            (window_title, row_id),
        )
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
            "SELECT start_ts, end_ts, duration_ms FROM intervals WHERE kind = 'pc_active'"
        ):
            total += _overlap_ms(
                float(row["start_ts"]),
                float(row["end_ts"]),
                int(row["duration_ms"]),
                q_from,
                q_to,
            )
        return total

    def totals_by_app(self, q_from: float, q_to: float) -> list[AppStat]:
        acc: dict[tuple[str, str], float] = {}
        for row in self._conn.execute(
            "SELECT exe_path, exe_name, start_ts, end_ts, duration_ms FROM intervals WHERE kind = 'app'"
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
        out = [
            AppStat(exe_name=name, exe_path=path, active_ms=v)
            for (path, name), v in acc.items()
            if v > 0.5
        ]
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

    # --- app categories ---
    def list_category_rules(self) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT id, match_text, match_kind, category, priority FROM app_category_rules ORDER BY priority DESC, id"
            ).fetchall()
        )

    def add_category_rule(
        self,
        match_text: str,
        match_kind: str,
        category: str,
        priority: int = 100,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO app_category_rules (match_text, match_kind, category, priority)
            VALUES (?, ?, ?, ?)
            """,
            (match_text.strip(), match_kind, category, priority),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def delete_category_rule(self, rule_id: int) -> None:
        self._conn.execute("DELETE FROM app_category_rules WHERE id = ?", (rule_id,))
        self._conn.commit()

    def resolve_category(self, exe_path: str) -> str:
        path_lower = exe_path.lower().replace("\\", "/")
        base = os.path.basename(path_lower)
        rows = self._conn.execute(
            "SELECT match_text, match_kind, category FROM app_category_rules ORDER BY priority DESC, id DESC"
        ).fetchall()
        for r in rows:
            mt = (r["match_text"] or "").lower()
            if not mt:
                continue
            if r["match_kind"] == "exact_basename" and base == mt:
                return str(r["category"])
            if r["match_kind"] == "path_contains" and mt in path_lower:
                return str(r["category"])
        return default_category_for_basename(base)

    def totals_by_category(self, q_from: float, q_to: float) -> dict[str, float]:
        acc = {PRODUCTIVE: 0.0, UNPRODUCTIVE: 0.0, NEUTRAL: 0.0}
        for a in self.totals_by_app(q_from, q_to):
            cat = self.resolve_category(a.exe_path)
            acc[cat] = acc.get(cat, 0.0) + a.active_ms
        return acc

    def bucket_pc_active_by_calendar_day(self, q_from: float, q_to: float) -> list[tuple[str, float]]:
        """List of (YYYY-MM-DD, active_ms) for each calendar day overlapping the range."""
        tz = datetime.now().astimezone().tzinfo
        d0 = datetime.fromtimestamp(q_from, tz=tz).date()
        d1 = datetime.fromtimestamp(q_to, tz=tz).date()
        out: list[tuple[str, float]] = []
        d = d0
        while d <= d1:
            day_start = datetime.combine(d, time(0, 0), tzinfo=tz)
            day_end = day_start + timedelta(days=1)
            ts0 = day_start.timestamp()
            ts1 = day_end.timestamp()
            q_a = max(q_from, ts0)
            q_b = min(q_to, ts1)
            ms = self.total_pc_ms(q_a, q_b) if q_b > q_a else 0.0
            out.append((d.isoformat(), ms))
            d += timedelta(days=1)
        return out

    def bucket_pc_active_by_hour_slots(
        self, q_from: float, q_to: float
    ) -> list[tuple[str, float]]:
        """Each local calendar hour in range: label 'dd HH:00' or 'YYYY-mm-dd HH:00', ms."""
        tz = datetime.now().astimezone().tzinfo
        out: list[tuple[str, float]] = []
        t = q_from
        while t < q_to:
            dt = datetime.fromtimestamp(t, tz=tz)
            hs = dt.replace(minute=0, second=0, microsecond=0)
            t0 = hs.timestamp()
            t1 = t0 + 3600.0
            ms = self.total_pc_ms(max(q_from, t0), min(q_to, t1))
            label = hs.strftime("%m-%d %H:00")
            out.append((label, ms))
            t = t1
        return out

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
