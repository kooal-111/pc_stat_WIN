from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pc_stat_win.config import default_db_path
from pc_stat_win.db import SCHEMA_VERSION
from pc_stat_win.main import _argv_without_background_flag, _run_packaged_smoke


class RuntimeConfigTests(unittest.TestCase):
    def test_database_path_can_be_redirected_for_packaged_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "smoke.sqlite"
            with patch.dict(os.environ, {"PCSTAT_DB_PATH": str(target)}):
                self.assertEqual(default_db_path(), target)

    def test_internal_flags_are_not_forwarded_to_qt(self) -> None:
        with patch("sys.argv", ["PCStat.exe", "--background", "--smoke-test", "--style", "fusion"]):
            self.assertEqual(
                _argv_without_background_flag(),
                ["PCStat.exe", "--style", "fusion"],
            )

    def test_packaged_smoke_creates_valid_database_without_qt_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "smoke.sqlite"

            self.assertEqual(_run_packaged_smoke(target), 0)

            conn = sqlite3.connect(target)
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT value FROM meta WHERE key = 'schema_version'"
                    ).fetchone()[0],
                    str(SCHEMA_VERSION),
                )
                self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM boot_log").fetchone()[0],
                    1,
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
