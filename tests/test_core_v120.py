from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from pc_stat_win.collector import UsageCollector
from pc_stat_win.db import BufferedInterval, Database, SCHEMA_VERSION
from pc_stat_win.foreground import ForegroundInfo
from pc_stat_win.idle import idle_seconds


class FakeClock:
    def __init__(self) -> None:
        self.wall = 1_000.0
        self.monotonic = 0.0

    def wall_time(self) -> float:
        return self.wall

    def monotonic_time(self) -> float:
        return self.monotonic

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.monotonic += seconds


FOREGROUND = ForegroundInfo(
    hwnd=1,
    pid=10,
    exe_path=r"C:\Apps\editor.exe",
    exe_name="editor.exe",
    window_title="Document",
)


def create_v5_database(path: Path, *, fail_migration: bool) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta (key, value) VALUES ('schema_version', '5');
        CREATE TABLE intervals (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          kind TEXT NOT NULL CHECK (kind IN ('pc_active', 'app')),
          exe_path TEXT,
          exe_name TEXT,
          window_title TEXT,
          start_ts REAL NOT NULL,
          end_ts REAL NOT NULL,
          duration_ms INTEGER NOT NULL
        );
        CREATE INDEX idx_intervals_kind_time
          ON intervals (kind, start_ts, end_ts);
        CREATE INDEX idx_intervals_pc_overlap
          ON intervals (start_ts, end_ts, duration_ms)
          WHERE kind = 'pc_active';
        CREATE INDEX idx_intervals_app_overlap
          ON intervals (start_ts, end_ts, exe_path, exe_name, duration_ms)
          WHERE kind = 'app';
        CREATE TABLE boot_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          boot_ts REAL NOT NULL,
          logged_at REAL NOT NULL
        );
        CREATE TABLE app_category_rules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          match_text TEXT NOT NULL,
          match_kind TEXT NOT NULL CHECK (
            match_kind IN ('exact_basename', 'path_contains')
          ),
          category TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_app_cat_rules_prio
          ON app_category_rules (priority DESC, id DESC);
        """
    )
    if fail_migration:
        conn.executescript(
            """
            CREATE TRIGGER fail_schema_v6
            BEFORE UPDATE OF value ON meta
            WHEN OLD.key = 'schema_version' AND NEW.value = '6'
            BEGIN
              SELECT RAISE(ABORT, 'forced migration failure');
            END;
            """
        )
    conn.commit()
    conn.close()


class DatabaseV120Tests(unittest.TestCase):
    def test_persist_usage_rolls_back_without_assigning_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            pc = BufferedInterval("pc_active", 10.0, 12.0, 2_000)
            invalid_app = BufferedInterval("pc_active", 10.0, 12.0, 2_000)

            with self.assertRaises(ValueError):
                db.persist_usage(pc, invalid_app)

            count = db._conn.execute("SELECT COUNT(*) FROM intervals").fetchone()[0]
            self.assertEqual(count, 0)
            self.assertIsNone(pc.row_id)
            self.assertIsNone(invalid_app.row_id)
            db.close()

    def test_v5_to_v6_migration_is_atomic_and_replaces_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.sqlite"
            create_v5_database(path, fail_migration=True)

            with self.assertRaises(sqlite3.IntegrityError):
                Database(path)

            conn = sqlite3.connect(path)
            try:
                version = conn.execute(
                    "SELECT value FROM meta WHERE key = 'schema_version'"
                ).fetchone()[0]
                indexes = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type = 'index' AND tbl_name = 'intervals'"
                    )
                }
                self.assertEqual(version, "5")
                self.assertIn("idx_intervals_kind_time", indexes)
                self.assertIn("idx_intervals_pc_overlap", indexes)
                self.assertIn("idx_intervals_app_overlap", indexes)
                self.assertNotIn("idx_intervals_kind_start", indexes)
                conn.execute("DROP TRIGGER fail_schema_v6")
                conn.commit()
            finally:
                conn.close()

            db = Database(path)
            self.assertEqual(db.get_setting("schema_version"), str(SCHEMA_VERSION))
            indexes = {
                row[0]
                for row in db._conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = 'intervals'"
                )
            }
            columns = [
                row[2]
                for row in db._conn.execute(
                    "PRAGMA index_info(idx_intervals_kind_start)"
                )
            ]
            self.assertEqual(indexes, {"idx_intervals_kind_start"})
            self.assertEqual(columns, ["kind", "start_ts"])
            self.assertEqual(db._conn.execute("PRAGMA synchronous").fetchone()[0], 1)
            db.close()

    def test_period_stats_includes_previous_pc_ms(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            for start, end, duration in ((0.0, 5.0, 5_000), (10.0, 18.0, 8_000)):
                db.insert_interval(
                    "pc_active",
                    exe_path=None,
                    exe_name=None,
                    window_title=None,
                    start_ts=start,
                    end_ts=end,
                    duration_ms=duration,
                )
            stats = db.period_stats(10.0, 20.0, previous_range=(0.0, 10.0))
            self.assertEqual(stats.pc_ms, 8_000.0)
            self.assertEqual(stats.previous_pc_ms, 5_000.0)
            db.close()


class CollectorV120Tests(unittest.TestCase):
    def make_collector(
        self,
        db: Database,
        clock: FakeClock,
        *,
        idle_provider=lambda: 0.0,
        foreground_provider=lambda: FOREGROUND,
    ) -> UsageCollector:
        return UsageCollector(
            db,
            wall_clock=clock.wall_time,
            monotonic_clock=clock.monotonic_time,
            idle_provider=idle_provider,
            foreground_provider=foreground_provider,
            boot_time_provider=lambda: 900.0,
        )

    def test_gap_flushes_buffer_without_counting_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            clock = FakeClock()
            collector = self.make_collector(db, clock)

            clock.advance(2.0)
            collector._on_tick()
            self.assertEqual(db.total_pc_ms(900.0, 1_100.0), 0.0)

            clock.advance(16.0)
            collector._on_tick()
            self.assertEqual(db.total_pc_ms(900.0, 1_100.0), 2_000.0)
            self.assertIsNone(collector._pc_row_id)
            self.assertIsNone(collector._app_row_id)
            db.close()

    def test_wall_clock_shift_closes_interval_without_counting_shift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            clock = FakeClock()
            collector = self.make_collector(db, clock)

            clock.advance(2.0)
            collector._on_tick()
            clock.monotonic += 2.0
            clock.wall += 302.0
            collector._on_tick()

            self.assertEqual(db.total_pc_ms(900.0, 2_000.0), 2_000.0)
            self.assertIsNone(collector._pc_row_id)
            db.close()

    def test_idle_failure_counts_nothing_and_emits_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            clock = FakeClock()
            foreground_calls: list[bool] = []
            collector = self.make_collector(
                db,
                clock,
                idle_provider=lambda: None,
                foreground_provider=lambda: foreground_calls.append(True),
            )
            errors: list[str] = []
            recoveries: list[bool] = []
            collector.error_occurred.connect(errors.append)
            collector.recovered.connect(lambda: recoveries.append(True))

            clock.advance(2.0)
            collector._on_tick()
            self.assertEqual(db.total_pc_ms(900.0, 1_100.0), 0.0)
            self.assertEqual(foreground_calls, [])
            self.assertEqual(len(errors), 1)

            collector._idle_provider = lambda: 0.0
            collector._foreground_provider = lambda: FOREGROUND
            clock.advance(2.0)
            collector._on_tick()
            collector.stop()
            self.assertEqual(db.total_pc_ms(900.0, 1_100.0), 2_000.0)
            self.assertEqual(recoveries, [True])
            db.close()


class IdleV120Tests(unittest.TestCase):
    def test_win32_idle_failure_returns_none(self) -> None:
        windll = SimpleNamespace(
            user32=SimpleNamespace(GetLastInputInfo=lambda _ptr: 0),
            kernel32=SimpleNamespace(GetTickCount=lambda: 0),
        )
        with patch("pc_stat_win.idle.ctypes.windll", windll, create=True):
            self.assertIsNone(idle_seconds())


if __name__ == "__main__":
    unittest.main()
