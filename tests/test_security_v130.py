from __future__ import annotations

import ast
import csv
import tempfile
import unittest
from pathlib import Path

from pc_stat_win.categories import BROWSER
from pc_stat_win.db import AppStat, Database, PeriodStats
from pc_stat_win.export import export_apps_csv, spreadsheet_safe_text


class SecurityV130Tests(unittest.TestCase):
    def test_title_opt_out_physically_removes_sensitive_text(self) -> None:
        sentinel = "PRIVATE-WINDOW-TITLE-9f83a1"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.sqlite"
            db = Database(path)
            db.set_collect_window_titles(True)
            db.insert_interval(
                "app",
                exe_path=r"C:\Apps\editor.exe",
                exe_name="editor.exe",
                window_title=sentinel,
                start_ts=1.0,
                end_ts=2.0,
                duration_ms=1_000,
            )
            db.set_collect_window_titles(False)
            self.assertIsNone(
                db._conn.execute("SELECT window_title FROM intervals").fetchone()[0]
            )
            db.close()

            needle = sentinel.encode("utf-8")
            for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
                if candidate.exists():
                    self.assertNotIn(needle, candidate.read_bytes(), str(candidate))

    def test_retention_and_full_history_delete_preserve_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            db.set_setting("ui_theme", "dark")
            db.insert_interval(
                "pc_active",
                exe_path=None,
                exe_name=None,
                window_title=None,
                start_ts=1.0,
                end_ts=2.0,
                duration_ms=1_000,
            )
            db.insert_interval(
                "pc_active",
                exe_path=None,
                exe_name=None,
                window_title=None,
                start_ts=2 * 86400.0,
                end_ts=2 * 86400.0 + 1.0,
                duration_ms=1_000,
            )
            db.set_retention_days(30)
            self.assertEqual(
                db.apply_retention_policy(now=31 * 86400.0),
                1,
            )
            self.assertEqual(db._conn.execute("SELECT COUNT(*) FROM intervals").fetchone()[0], 1)
            self.assertEqual(db.delete_all_history(), 1)
            self.assertEqual(db._conn.execute("SELECT COUNT(*) FROM intervals").fetchone()[0], 0)
            self.assertEqual(db.get_setting("ui_theme"), "dark")
            db.close()

    def test_spreadsheet_formula_prefixes_are_neutralized(self) -> None:
        for value in ("=2+2", "+cmd", "-1+2", "@SUM(A1:A2)", "\t=cmd"):
            self.assertTrue(spreadsheet_safe_text(value).startswith("'"))
        self.assertEqual(spreadsheet_safe_text("chrome.exe"), "chrome.exe")

    def test_export_neutralizes_user_controlled_application_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "data.sqlite")
            stats = PeriodStats(
                q_from=0.0,
                q_to=10.0,
                pc_ms=1_000.0,
                apps=[AppStat("=cmd.exe", "=2+2.exe", 1_000.0, BROWSER)],
                by_category={BROWSER: 1_000.0},
                chart_mode="hour",
                chart_series=[],
                estimated_uptime_sec=10.0,
            )
            target = Path(tmp) / "report.csv"
            export_apps_csv(db, 0.0, 10.0, str(target), stats)
            with target.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream, delimiter=";"))
            self.assertTrue(rows[1][0].startswith("'"))
            self.assertTrue(rows[1][1].startswith("'"))
            db.close()

    def test_runtime_has_no_outbound_network_client_imports(self) -> None:
        root = Path(__file__).resolve().parents[1] / "pc_stat_win"
        forbidden = {
            "aiohttp",
            "http.client",
            "httpx",
            "requests",
            "socket",
            "urllib.request",
            "websocket",
        }
        found: set[str] = set()
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    found.update(alias.name for alias in node.names if alias.name in forbidden)
                elif isinstance(node, ast.ImportFrom) and node.module in forbidden:
                    found.add(str(node.module))
        self.assertEqual(found, set())


if __name__ == "__main__":
    unittest.main()
