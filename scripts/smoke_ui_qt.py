"""Qt smoke: create MainWindow, processEvents, exit (CI / local sanity)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from pc_stat_win.branding import app_icon
from pc_stat_win.collector import UsageCollector
from pc_stat_win.config import POLL_INTERVAL_MS, ensure_app_dirs
from pc_stat_win.db import Database
from pc_stat_win.ui.main_window import MainWindow
from pc_stat_win.ui.styles import load_stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    db_path = ensure_app_dirs()
    db = Database(db_path)
    theme = db.get_setting("ui_theme", "dark") or "dark"
    if theme not in ("dark", "light"):
        theme = "dark"
    app.setStyleSheet(load_stylesheet(theme))
    icon = app_icon()
    col = UsageCollector(db, poll_interval_ms=POLL_INTERVAL_MS)
    win = MainWindow(db, col, window_icon=icon)
    win.show()
    app.processEvents()
    win.close()
    col.stop()
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
