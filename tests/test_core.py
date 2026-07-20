from __future__ import annotations

import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from pc_stat_win.categories import BROWSER, FILES, REMOTE_ACCESS
from pc_stat_win.config import SYSTEM32_SILENT_EXES
from pc_stat_win.db import Database, SCHEMA_VERSION, _overlap_ms
from pc_stat_win.periods import period_range, period_title, previous_period_range
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

    def test_calendar_period_offsets_and_russian_titles(self) -> None:
        tz = datetime.now().astimezone().tzinfo
        now = datetime(2026, 7, 20, 15, 30, tzinfo=tz).timestamp()

        day_from, day_to = period_range("today", offset=-1, now=now)
        self.assertEqual(datetime.fromtimestamp(day_from, tz=tz).date().isoformat(), "2026-07-19")
        self.assertEqual(datetime.fromtimestamp(day_to, tz=tz).date().isoformat(), "2026-07-20")
        self.assertEqual(period_title("today", day_from, day_to, now=now), "Вчера, 19 июля")

        week_from, week_to = period_range("week", offset=-1, now=now)
        self.assertEqual(datetime.fromtimestamp(week_from, tz=tz).date().isoformat(), "2026-07-13")
        self.assertEqual(datetime.fromtimestamp(week_to, tz=tz).date().isoformat(), "2026-07-20")
        self.assertEqual(period_title("week", week_from, week_to, now=now), "13–19 июля 2026")

        month_from, month_to = period_range("month", offset=-1, now=now)
        self.assertEqual(datetime.fromtimestamp(month_from, tz=tz).date().isoformat(), "2026-06-01")
        self.assertEqual(datetime.fromtimestamp(month_to, tz=tz).date().isoformat(), "2026-07-01")
        self.assertEqual(period_title("month", month_from, month_to, now=now), "Июнь 2026")

        year_from, year_to = period_range("year", offset=-1, now=now)
        self.assertEqual(datetime.fromtimestamp(year_from, tz=tz).year, 2025)
        self.assertEqual(datetime.fromtimestamp(year_to, tz=tz).year, 2026)
        self.assertEqual(period_title("year", year_from, year_to, now=now), "2025 год")

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

    def test_period_stats_builds_calendar_category_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            tz = datetime.now().astimezone().tzinfo
            q_from = datetime(2026, 7, 13, tzinfo=tz).timestamp()
            q_to = q_from + 9 * 3600
            start = q_from + 3600
            end = start + 7200
            db.insert_interval(
                "pc_active",
                exe_path=None,
                exe_name=None,
                window_title=None,
                start_ts=start,
                end_ts=end,
                duration_ms=7_200_000,
            )
            db.insert_interval(
                "app",
                exe_path=r"C:\Program Files\Google\Chrome\chrome.exe",
                exe_name="chrome.exe",
                window_title=None,
                start_ts=start,
                end_ts=end,
                duration_ms=7_200_000,
            )

            stats = db.period_stats(q_from, q_to, chart_period="week")

            self.assertEqual(stats.chart_mode, "day")
            self.assertEqual(len(stats.chart_series), 7)
            self.assertAlmostEqual(sum(stats.chart_by_category[BROWSER]), 7_200_000.0)
            self.assertAlmostEqual(
                sum(value for _label, value in stats.chart_series), 7_200_000.0
            )
            db.close()

    def test_report_granularity_uses_full_calendar_axis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            tz = datetime.now().astimezone().tzinfo
            cases = (
                ("today", datetime(2026, 7, 20, tzinfo=tz), 24, "hour"),
                ("week", datetime(2026, 7, 20, tzinfo=tz), 7, "day"),
                ("month", datetime(2026, 7, 1, tzinfo=tz), 31, "day"),
                ("year", datetime(2026, 1, 1, tzinfo=tz), 12, "month"),
            )
            for period, start, expected_count, expected_mode in cases:
                with self.subTest(period=period):
                    q_from = start.timestamp()
                    stats = db.period_stats(
                        q_from,
                        q_from + 3600,
                        chart_period=period,
                    )
                    self.assertEqual(stats.chart_mode, expected_mode)
                    self.assertEqual(len(stats.chart_series), expected_count)
            db.close()


if __name__ == "__main__":
    unittest.main()
