"""Offscreen UI smoke for pages, themes and compact desktop geometry."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if os.environ.get("PCSTAT_UI_NATIVE", "").strip() != "1":
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QScrollArea

from pc_stat_win.branding import app_icon
from pc_stat_win.collector import UsageCollector
from pc_stat_win.config import POLL_INTERVAL_MS
from pc_stat_win.db import Database
from pc_stat_win.ui.main_window import MainWindow
from pc_stat_win.ui.theme_manager import ThemeManager


def _seed_long_ui_data(db: Database) -> None:
    now = time.time()
    db.insert_interval(
        "pc_active",
        exe_path=None,
        exe_name=None,
        window_title=None,
        start_ts=now - 28_800,
        end_ts=now,
        duration_ms=28_800_000,
    )
    for index in range(18):
        duration_ms = (index + 1) * 180_000
        db.insert_interval(
            "app",
            exe_path=(
                rf"C:\Program Files\Long Vendor and Product Name {index:02d}"
                rf"\application-with-a-long-name-{index:02d}.exe"
            ),
            exe_name=f"application-with-a-long-name-{index:02d}.exe",
            window_title=f"Long document title {index:02d} " + "x" * 80,
            start_ts=now - (index + 1) * 900,
            end_ts=now - index * 300,
            duration_ms=duration_ms,
        )
        db.add_category_rule(
            f"smoke-rule-{index:02d}.exe",
            "exact_basename",
            "browser" if index % 2 else "devtools",
        )


def _assert_no_horizontal_overflow(window: MainWindow, page: int) -> None:
    for scroll in window.findChildren(QScrollArea):
        if not scroll.isVisible():
            continue
        if scroll.horizontalScrollBar().maximum() != 0:
            inner = scroll.widget()
            raise AssertionError(
                f"page {page} has a horizontal page scrollbar: "
                f"{scroll.objectName() or type(scroll).__name__}, "
                f"inner={inner.width() if inner else 'n/a'}, "
                f"viewport={scroll.viewport().width()}, "
                f"maximum={scroll.horizontalScrollBar().maximum()}"
            )
        inner = scroll.widget()
        if inner is not None and inner.width() > scroll.viewport().width() + 1:
            raise AssertionError(f"page {page} content is wider than its viewport")
    if page == window.PAGE_STATS and window._table.horizontalScrollBar().maximum() != 0:
        raise AssertionError("statistics table overflows horizontally")
    if page == window.PAGE_CATEGORIES and window._rules_table.horizontalScrollBar().maximum() != 0:
        raise AssertionError("category rules table overflows horizontally")


def main() -> int:
    app = QApplication(sys.argv)
    with tempfile.TemporaryDirectory(prefix="pc_stat_smoke_") as tmp:
        db = Database(Path(tmp) / "data.sqlite")
        _seed_long_ui_data(db)
        collector = UsageCollector(db, poll_interval_ms=POLL_INTERVAL_MS)
        themes = ThemeManager(app, "system")
        window = MainWindow(db, collector, window_icon=app_icon(), tray_available=False)
        themes.register_window(window)
        themes.theme_changed.connect(window.apply_theme)
        window.theme_changed.connect(themes.set_mode)

        try:
            screenshot_root_value = os.environ.get("PCSTAT_UI_SCREENSHOTS", "").strip()
            screenshot_root = Path(screenshot_root_value) if screenshot_root_value else None
            if screenshot_root is not None:
                screenshot_root.mkdir(parents=True, exist_ok=True)

            for width, height in ((760, 520), (920, 640), (1280, 800)):
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
                        if window.width() != width or window.height() != height:
                            raise AssertionError(
                                f"requested {width}x{height}, got {window.width()}x{window.height()}"
                            )
                        _assert_no_horizontal_overflow(window, page)
                        if width == 760 and page == window.PAGE_STATS:
                            if window._top_surface.isVisible() or window._table.height() < 220:
                                raise AssertionError(
                                    "compact statistics page leaves too little table space"
                                )
                        if screenshot_root is not None:
                            resolved = themes.resolved_theme
                            output = screenshot_root / (
                                f"{width}x{height}-{mode}-{resolved}-page-{page}.png"
                            )
                            if not window.grab().save(str(output)):
                                raise AssertionError(f"unable to save screenshot {output}")
        finally:
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
            window.close()
            collector.stop()
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
