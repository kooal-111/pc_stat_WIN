from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from pc_stat_win.categories import BROWSER, FILES, REMOTE_ACCESS
from pc_stat_win.config import SYSTEM32_SILENT_EXES
from pc_stat_win.db import Database, SCHEMA_VERSION, _overlap_ms
from pc_stat_win.periods import period_range, previous_period_range
from pc_stat_win.process_filter import should_track_foreground


class CoreTests(unittest.TestCase):
    def test_overlap_ms_partial(self) -> None:
        self.assertEqual(_overlap_ms(0.0, 10.0, 10000, 2.0, 5.0), 3000.0)
        self.assertEqual(_overlap_ms(0.0, 10.0, 10000, 10.0, 20.0), 0.0)

    def test_period_ranges_are_valid(self) -> None:
        for key in ("today", "week", "month", "year"):
            start, end = period_range(key)  # type: ignore[arg-type]
            self.assertLess(start, end)
            self.assertIsNotNone(previous_period_range(key, start, end))  # type: ignore[arg-type]

    def test_process_filter_uses_lowercase_system_exes(self) -> None:
        self.assertIn("runtimebroker.exe", SYSTEM32_SILENT_EXES)
        self.assertFalse(
            should_track_foreground(
                r"C:\Windows\System32\RuntimeBroker.exe",
                "RuntimeBroker.exe",
                frozenset(),
            )
        )

    def test_default_categories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            self.assertEqual(db.resolve_category(r"C:\Program Files\Google\Chrome\Application\chrome.exe"), BROWSER)
            self.assertEqual(db.resolve_category(r"C:\Windows\explorer.exe"), FILES)
            self.assertEqual(db.resolve_category(r"C:\Windows\System32\mstsc.exe"), REMOTE_ACCESS)
            db.close()

    def test_path_contains_normalizes_slashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            db.add_category_rule(r"C:\Tools\Remote", "path_contains", REMOTE_ACCESS)
            self.assertEqual(db.resolve_category("c:/tools/remote/app.exe"), REMOTE_ACCESS)
            db.close()

    def test_v4_to_v5_migration_preserves_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.sqlite"
            conn = sqlite3.connect(path)
            conn.executescript(
                """
                CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT INTO meta (key, value) VALUES ('schema_version', '4');
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
                CREATE TABLE boot_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  boot_ts REAL NOT NULL,
                  logged_at REAL NOT NULL
                );
                CREATE TABLE app_category_rules (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  match_text TEXT NOT NULL,
                  match_kind TEXT NOT NULL CHECK (match_kind IN ('exact_basename', 'path_contains')),
                  category TEXT NOT NULL CHECK (category IN (
                    'work','distraction','communication','games','media','devtools','system','other'
                  )),
                  priority INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO app_category_rules (match_text, match_kind, category, priority)
                VALUES ('chrome.exe', 'exact_basename', 'other', 100);
                """
            )
            conn.commit()
            conn.close()

            db = Database(path)
            self.assertEqual(db.get_setting("schema_version"), str(SCHEMA_VERSION))
            db.add_category_rule("firefox.exe", "exact_basename", BROWSER)
            rules = db.list_category_rules()
            self.assertGreaterEqual(len(rules), 2)
            db.close()

    def test_period_stats_filters_by_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            now = time.time()
            db.insert_interval(
                "pc_active",
                exe_path=None,
                exe_name=None,
                window_title=None,
                start_ts=now - 100,
                end_ts=now - 50,
                duration_ms=50000,
            )
            db.insert_interval(
                "pc_active",
                exe_path=None,
                exe_name=None,
                window_title=None,
                start_ts=now - 10,
                end_ts=now,
                duration_ms=10000,
            )
            stats = db.period_stats(now - 20, now)
            self.assertAlmostEqual(stats.pc_ms, 10000.0)
            db.close()


if __name__ == "__main__":
    unittest.main()
