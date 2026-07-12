"""Offscreen UI smoke for pages, themes and compact desktop geometry."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from pc_stat_win.branding import app_icon
from pc_stat_win.collector import UsageCollector
from pc_stat_win.config import POLL_INTERVAL_MS
from pc_stat_win.db import Database
from pc_stat_win.ui.main_window import MainWindow
from pc_stat_win.ui.theme_manager import ThemeManager


def main() -> int:
    app = QApplication(sys.argv)
    with tempfile.TemporaryDirectory(prefix="pc_stat_smoke_") as tmp:
        db = Database(Path(tmp) / "data.sqlite")
        collector = UsageCollector(db, poll_interval_ms=POLL_INTERVAL_MS)
        themes = ThemeManager(app, "system")
        window = MainWindow(db, collector, window_icon=app_icon(), tray_available=False)
        themes.register_window(window)
        themes.theme_changed.connect(window.apply_theme)
        window.theme_changed.connect(themes.set_mode)

        for width, height in ((920, 640), (1280, 800)):
            window.resize(width, height)
            window.show()
            app.processEvents()
            for mode in ("dark", "light", "system"):
                themes.set_mode(mode)
                app.processEvents()
                for page in range(window._stack.count()):
                    window._set_page(page)
                    app.processEvents()
                    if window._stack.currentWidget().width() <= 0:
                        raise AssertionError(f"page {page} has invalid geometry")

        window.close()
        collector.stop()
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
