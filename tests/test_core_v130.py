from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pc_stat_win.categories import BROWSER, WORK
from pc_stat_win.collector import UsageCollector
from pc_stat_win.db import BufferedInterval, Database, SCHEMA_VERSION
from pc_stat_win.foreground import ForegroundInfo


class FakeClock:
    def __init__(self, wall: float = 1_000.0) -> None:
        self.wall = wall
        self.monotonic = 0.0

    def wall_time(self) -> float:
        return self.wall

    def monotonic_time(self) -> float:
        return self.monotonic

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.monotonic += seconds


def foreground(name: str, title: str = "") -> ForegroundInfo:
    return ForegroundInfo(
        hwnd=1,
        pid=1,
        exe_path=rf"C:\Apps\{name}",
        exe_name=name,
        window_title=title,
    )


def create_v6_database(path: Path, *, fail_v7: bool = False) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO meta (key, value) VALUES ('schema_version', '6');
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
        CREATE INDEX idx_intervals_kind_start
          ON intervals (kind, start_ts);
        INSERT INTO intervals (
          kind, exe_path, exe_name, window_title,
          start_ts, end_ts, duration_ms
        ) VALUES (
          'app', 'C:\\Apps\\private.exe', 'private.exe',
          'Private document - chat', 100, 101, 1000
        );
        CREATE TABLE boot_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          boot_ts REAL NOT NULL,
          logged_at REAL NOT NULL
        );
        INSERT INTO boot_log (boot_ts, logged_at) VALUES (100, 125);
        CREATE TABLE app_category_rules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          match_text TEXT NOT NULL,
          match_kind TEXT NOT NULL,
          category TEXT NOT NULL,
          priority INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX idx_app_cat_rules_prio
          ON app_category_rules (priority DESC, id DESC);
        INSERT INTO app_category_rules
          (id, match_text, match_kind, category, priority)
        VALUES
          (1, ' Chrome.EXE ', 'exact_basename', 'browser', 10),
          (2, 'chrome.exe', 'exact_basename', 'work', 20),
          (3, 'C:\\Tools\\AI', 'path_contains', 'ai_tools', 5);
        """
    )
    if fail_v7:
        conn.executescript(
            """
            CREATE TRIGGER fail_schema_v7
            BEFORE UPDATE OF value ON meta
            WHEN NEW.key = 'schema_version' AND NEW.value = '7'
            BEGIN
              SELECT RAISE(ABORT, 'injected v7 migration failure');
            END;
            """
        )
    conn.commit()
    conn.close()


class DatabaseV130Tests(unittest.TestCase):
    def test_fresh_database_is_created_directly_at_v7(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.sqlite"
            with patch.object(
                Database,
                "_apply_migrations",
                side_effect=AssertionError("fresh database ran historical migrations"),
            ):
                db = Database(path)

            self.assertEqual(SCHEMA_VERSION, 7)
            self.assertEqual(db.get_setting("schema_version"), "7")
            self.assertFalse(db.get_collect_window_titles())
            boot_columns = {
                row[1] for row in db._conn.execute("PRAGMA table_info(boot_log)")
            }
            self.assertIn("last_seen_ts", boot_columns)
            self.assertEqual(db._conn.execute("PRAGMA busy_timeout").fetchone()[0], 500)
            self.assertEqual(
                db._conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0], 256
            )
            self.assertEqual(
                db._conn.execute("PRAGMA journal_size_limit").fetchone()[0],
                8 * 1024 * 1024,
            )
            db.close()

    def test_v6_to_v7_migration_rolls_back_schema_and_dedup_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.sqlite"
            create_v6_database(path, fail_v7=True)

            with self.assertRaises(sqlite3.IntegrityError):
                Database(path)

            conn = sqlite3.connect(path)
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT value FROM meta WHERE key = 'schema_version'"
                    ).fetchone()[0],
                    "6",
                )
                columns = {
                    row[1] for row in conn.execute("PRAGMA table_info(boot_log)")
                }
                self.assertNotIn("last_seen_ts", columns)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM app_category_rules").fetchone()[0],
                    3,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT window_title FROM intervals WHERE exe_name = 'private.exe'"
                    ).fetchone()[0],
                    "Private document - chat",
                )
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type = 'index' "
                        "AND name = 'idx_app_cat_rules_normalized_unique'"
                    ).fetchone()
                )
                conn.execute("DROP TRIGGER fail_schema_v7")
                conn.commit()
            finally:
                conn.close()

            db = Database(path)
            self.assertEqual(db.get_setting("schema_version"), "7")
            rows = db._conn.execute(
                "SELECT id, match_text FROM app_category_rules ORDER BY id"
            ).fetchall()
            self.assertEqual([(row["id"], row["match_text"]) for row in rows], [
                (2, "chrome.exe"),
                (3, "c:/tools/ai"),
            ])
            boot = db._conn.execute(
                "SELECT boot_ts, logged_at, last_seen_ts FROM boot_log"
            ).fetchone()
            self.assertEqual(float(boot["last_seen_ts"]), 125.0)
            self.assertIsNone(
                db._conn.execute(
                    "SELECT window_title FROM intervals WHERE exe_name = 'private.exe'"
                ).fetchone()[0]
            )
            self.assertFalse(db.get_collect_window_titles())
            db.close()

    def test_v1_database_migrates_to_v7(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.sqlite"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO meta (key, value) VALUES ('schema_version', '1');
                CREATE TABLE intervals (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  kind TEXT NOT NULL,
                  exe_path TEXT,
                  exe_name TEXT,
                  window_title TEXT,
                  start_ts REAL NOT NULL,
                  end_ts REAL NOT NULL,
                  duration_ms INTEGER NOT NULL
                );
                CREATE TABLE boot_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  boot_ts REAL NOT NULL,
                  logged_at REAL NOT NULL
                );
                """
            )
            conn.commit()
            conn.close()

            db = Database(path)
            self.assertEqual(db.get_setting("schema_version"), "7")
            self.assertIn(
                "last_seen_ts",
                {row[1] for row in db._conn.execute("PRAGMA table_info(boot_log)")},
            )
            db.close()

    def test_normalized_rule_index_rejects_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            first_id = db.add_category_rule(
                r"C:\Programs\Chrome.EXE", "exact_basename", BROWSER
            )
            self.assertGreater(first_id, 0)
            with self.assertRaises(sqlite3.IntegrityError):
                db.add_category_rule(" chrome.exe ", "exact_basename", WORK)
            self.assertEqual(len(db.list_category_rules()), 1)
            self.assertEqual(
                db.persist_usage(
                    [BufferedInterval("pc_active", 1.0, 2.0, 1_000)]
                ),
                [1],
            )
            db.close()

    def test_uptime_excludes_off_time_between_historical_boots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            db._conn.executemany(
                """
                INSERT INTO boot_log (boot_ts, logged_at, last_seen_ts)
                VALUES (?, ?, ?)
                """,
                ((100.0, 110.0, 150.0), (300.0, 305.0, 330.0)),
            )
            db._conn.commit()
            with patch("pc_stat_win.db.time.time", return_value=340.0):
                self.assertEqual(db.estimated_pc_uptime_seconds(0.0, 400.0), 90.0)
            db.close()

    def test_persist_usage_returns_ordered_ids_and_updates_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            db.set_collect_window_titles(True)
            batch = [
                BufferedInterval("app", 1.0, 2.0, 1_000, "a", "a.exe", "Old"),
                BufferedInterval("pc_active", 1.0, 3.0, 2_000),
                BufferedInterval("app", 2.0, 3.0, 1_000, "b", "b.exe", "B"),
            ]
            ids = db.persist_usage(batch)
            self.assertIsInstance(ids, list)
            self.assertEqual(len(ids), 3)
            stored = db._conn.execute(
                "SELECT id, kind FROM intervals ORDER BY id"
            ).fetchall()
            self.assertEqual(
                [(row["id"], row["kind"]) for row in stored],
                list(zip(ids, ["app", "pc_active", "app"])),
            )

            updated = replace(batch[0], row_id=ids[0], end_ts=4.0, duration_ms=3_000,
                              window_title="New")
            self.assertEqual(db.persist_usage([updated]), [ids[0]])
            row = db._conn.execute(
                "SELECT duration_ms, window_title FROM intervals WHERE id = ?",
                (ids[0],),
            ).fetchone()
            self.assertEqual((row["duration_ms"], row["window_title"]), (3_000, "New"))
            db.close()

    def test_persist_usage_rolls_back_whole_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            db._conn.execute(
                """
                CREATE TRIGGER reject_bad_interval
                BEFORE INSERT ON intervals WHEN NEW.exe_name = 'bad.exe'
                BEGIN SELECT RAISE(ABORT, 'injected insert failure'); END
                """
            )
            db._conn.commit()
            batch = [
                BufferedInterval("app", 1.0, 2.0, 1_000, "a", "good.exe"),
                BufferedInterval("app", 2.0, 3.0, 1_000, "b", "bad.exe"),
            ]
            with self.assertRaises(sqlite3.IntegrityError):
                db.persist_usage(batch)
            self.assertEqual(
                db._conn.execute("SELECT COUNT(*) FROM intervals").fetchone()[0], 0
            )
            self.assertTrue(all(item.row_id is None for item in batch))
            db.close()


class CollectorV130Tests(unittest.TestCase):
    def make_collector(
        self,
        db: Database,
        clock: FakeClock,
        foreground_provider,
        *,
        stop_retry_attempts: int = 3,
    ) -> UsageCollector:
        return UsageCollector(
            db,
            wall_clock=clock.wall_time,
            monotonic_clock=clock.monotonic_time,
            idle_provider=lambda: 0.0,
            foreground_provider=foreground_provider,
            boot_time_provider=lambda: 900.0,
            stop_retry_attempts=stop_retry_attempts,
            retry_sleep=lambda _seconds: None,
        )

    def test_window_titles_are_private_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            clock = FakeClock()
            collector = self.make_collector(
                db,
                clock,
                lambda: foreground("chat.exe", "Private conversation"),
            )
            clock.advance(2.0)
            collector._on_tick()
            self.assertTrue(collector.stop())

            title = db._conn.execute(
                "SELECT window_title FROM intervals WHERE kind = 'app'"
            ).fetchone()[0]
            self.assertIsNone(title)
            db.close()

    def test_window_titles_require_explicit_opt_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            db.set_collect_window_titles(True)
            clock = FakeClock()
            collector = self.make_collector(
                db,
                clock,
                lambda: foreground("editor.exe", "Roadmap.md"),
            )
            clock.advance(2.0)
            collector._on_tick()
            self.assertTrue(collector.stop())

            title = db._conn.execute(
                "SELECT window_title FROM intervals WHERE kind = 'app'"
            ).fetchone()[0]
            self.assertEqual(title, "Roadmap.md")
            db.close()

    def test_reload_settings_scrubs_buffered_title_after_opt_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            db.set_collect_window_titles(True)
            clock = FakeClock()
            collector = self.make_collector(
                db,
                clock,
                lambda: foreground("editor.exe", "Confidential.md"),
            )
            clock.advance(2.0)
            collector._on_tick()
            self.assertEqual(collector._app_interval.window_title, "Confidential.md")

            db.set_collect_window_titles(False)
            collector.reload_settings()
            self.assertIsNone(collector._app_interval.window_title)
            self.assertTrue(collector.stop())
            self.assertIsNone(
                db._conn.execute(
                    "SELECT window_title FROM intervals WHERE kind = 'app'"
                ).fetchone()[0]
            )
            db.close()

    def test_failed_periodic_commit_keeps_every_sample_and_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            clock = FakeClock()
            active = {"app": foreground("a.exe", "A")}
            collector = self.make_collector(db, clock, lambda: active["app"])
            real_persist = db.persist_usage
            calls = 0

            def fail_once(intervals):
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise sqlite3.OperationalError("injected commit failure")
                return real_persist(intervals)

            with patch.object(db, "persist_usage", side_effect=fail_once):
                for tick in range(15):
                    active["app"] = foreground(f"{tick % 2}.exe", str(tick))
                    clock.advance(2.0)
                    collector._on_tick()

                self.assertEqual(db.total_pc_ms(900.0, 1_100.0), 0.0)
                buffered_ms = sum(
                    interval.duration_ms for interval in collector._pending_intervals
                )
                buffered_ms += collector._pc_interval.duration_ms
                self.assertEqual(buffered_ms, 58_000)
                self.assertTrue(
                    all(item.row_id is None for item in collector._pending_intervals)
                )
                self.assertIsNone(collector._pc_row_id)

                active["app"] = foreground("next.exe", "Next")
                clock.advance(2.0)
                collector._on_tick()

            self.assertEqual(db.total_pc_ms(900.0, 1_100.0), 32_000.0)
            self.assertEqual(
                sum(app.active_ms for app in db.totals_by_app(900.0, 1_100.0)),
                32_000.0,
            )
            self.assertEqual(collector._pending_intervals, [])
            self.assertIsNotNone(collector._pc_row_id)
            db.close()

    def test_stop_retries_flush_and_touches_last_seen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            clock = FakeClock()
            collector = self.make_collector(
                db, clock, lambda: foreground("editor.exe", "Draft")
            )
            clock.advance(2.0)
            collector._on_tick()
            real_persist = db.persist_usage
            calls = 0

            def fail_twice(intervals):
                nonlocal calls
                calls += 1
                if calls < 3:
                    raise sqlite3.OperationalError("database is busy")
                return real_persist(intervals)

            with patch.object(db, "persist_usage", side_effect=fail_twice):
                self.assertTrue(collector.stop())

            self.assertEqual(calls, 3)
            self.assertEqual(db.total_pc_ms(900.0, 1_100.0), 2_000.0)
            last_seen = db._conn.execute(
                "SELECT last_seen_ts FROM boot_log ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
            self.assertEqual(float(last_seen), clock.wall)
            db.close()

    def test_failed_stop_retains_pending_intervals_and_returns_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            clock = FakeClock()
            collector = self.make_collector(
                db,
                clock,
                lambda: foreground("editor.exe"),
                stop_retry_attempts=2,
            )
            clock.advance(2.0)
            collector._on_tick()

            with patch.object(
                db,
                "persist_usage",
                side_effect=sqlite3.OperationalError("database is busy"),
            ) as persist:
                self.assertFalse(collector.stop())

            self.assertEqual(persist.call_count, 2)
            self.assertEqual(db.total_pc_ms(900.0, 1_100.0), 0.0)
            self.assertEqual(
                sum(item.duration_ms for item in collector._pending_intervals), 4_000
            )
            self.assertTrue(
                all(item.row_id is None for item in collector._pending_intervals)
            )
            db.close()

    def test_rapid_switches_stay_within_transaction_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            clock = FakeClock()
            active = {"app": foreground("0.exe")}
            collector = self.make_collector(db, clock, lambda: active["app"])
            transactions = 0

            def trace(sql: str) -> None:
                nonlocal transactions
                if sql.strip().upper().startswith("BEGIN IMMEDIATE"):
                    transactions += 1

            db._conn.set_trace_callback(trace)
            for tick in range(60):
                active["app"] = foreground(f"{tick % 2}.exe", str(tick))
                clock.advance(2.0)
                collector._on_tick()
            self.assertTrue(collector.stop())
            db._conn.set_trace_callback(None)

            self.assertLessEqual(transactions, 7)
            self.assertEqual(db.total_pc_ms(900.0, 1_200.0), 120_000.0)
            self.assertEqual(
                sum(app.active_ms for app in db.totals_by_app(900.0, 1_200.0)),
                120_000.0,
            )
            self.assertEqual(
                db._conn.execute(
                    "SELECT COUNT(*) FROM intervals WHERE kind = 'app'"
                ).fetchone()[0],
                60,
            )
            db.close()


if __name__ == "__main__":
    unittest.main()
