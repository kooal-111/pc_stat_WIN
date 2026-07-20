"""Capture README screenshots from a temporary database with synthetic data."""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
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
from pc_stat_win.categories import (
    AI_TOOLS,
    BROWSER,
    COMMUNICATION,
    CREATIVE,
    DEVTOOLS,
    FILES,
    OFFICE_DOCS,
)
from pc_stat_win.collector import UsageCollector
from pc_stat_win.db import Database
from pc_stat_win.ui.main_window import MainWindow
from pc_stat_win.ui.theme_manager import ThemeManager


OUTPUT_DIR = ROOT / "docs" / "images"
APP_SPECS = (
    ("Visual Studio Code", "Visual Studio Code.exe", DEVTOOLS, 2.60),
    ("Google Chrome", "Google Chrome.exe", BROWSER, 1.45),
    ("Telegram", "Telegram.exe", COMMUNICATION, 0.65),
    ("Figma", "Figma.exe", CREATIVE, 0.55),
    ("Microsoft Word", "Microsoft Word.exe", OFFICE_DOCS, 0.45),
    ("Проводник", "Проводник.exe", FILES, 0.30),
    ("ChatGPT", "ChatGPT.exe", AI_TOOLS, 0.25),
)
DAY_FACTORS = (1.00, 0.92, 1.08, 0.96, 1.12, 0.62, 0.48)


def _local_midnight(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _seed_week(db: Database, monday: datetime, scale: float) -> None:
    for day_index, day_factor in enumerate(DAY_FACTORS):
        day = monday + timedelta(days=day_index)
        cursor = day.replace(hour=8, minute=45)
        pc_start = cursor.timestamp()
        with db.transaction():
            for display_name, filename, _category, hours in APP_SPECS:
                duration_seconds = int(hours * day_factor * scale * 3600)
                start_ts = cursor.timestamp()
                cursor += timedelta(seconds=duration_seconds)
                db.insert_interval(
                    "app",
                    exe_path=rf"C:\Program Files\PC Stat Demo\{filename}",
                    exe_name=display_name,
                    window_title=None,
                    start_ts=start_ts,
                    end_ts=cursor.timestamp(),
                    duration_ms=duration_seconds * 1000,
                    commit=False,
                )
            pc_end = (cursor + timedelta(minutes=35)).timestamp()
            db.insert_interval(
                "pc_active",
                exe_path=None,
                exe_name=None,
                window_title=None,
                start_ts=pc_start,
                end_ts=pc_end,
                duration_ms=int((pc_end - pc_start) * 1000),
                commit=False,
            )
        db.log_boot_if_new(pc_start - 30 * 60, pc_end + 10 * 60)


def _seed_demo_data(db: Database, now: datetime) -> None:
    for _display_name, filename, category, _hours in APP_SPECS:
        db.add_category_rule(filename, "exact_basename", category)

    current_monday = _local_midnight(now) - timedelta(days=now.weekday())
    _seed_week(db, current_monday - timedelta(days=14), 0.82)
    _seed_week(db, current_monday - timedelta(days=7), 1.00)


def _settle(app: QApplication, cycles: int = 8) -> None:
    for _ in range(cycles):
        app.processEvents()


def _save_window(window: MainWindow, path: Path) -> None:
    _settle(QApplication.instance())
    pixmap = window.grab()
    if pixmap.isNull() or not pixmap.save(str(path), "PNG"):
        raise OSError(f"Unable to save screenshot: {path}")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setApplicationName("PC Stat")
    now = datetime.now().astimezone()

    with tempfile.TemporaryDirectory(prefix="pcstat_readme_") as tmp:
        db = Database(Path(tmp) / "demo.sqlite")
        _seed_demo_data(db, now)
        collector = UsageCollector(
            db,
            wall_clock=lambda: now.timestamp(),
            boot_time_provider=lambda: now.timestamp() - 2 * 3600,
        )
        themes = ThemeManager(app, "light")
        window = MainWindow(db, collector, window_icon=app_icon(), tray_available=False)
        themes.register_window(window)
        themes.theme_changed.connect(window.apply_theme)
        window.theme_changed.connect(themes.set_mode)
        window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        window.resize(1280, 800)
        window.show()

        try:
            themes.set_mode("light")
            window._set_page(window.PAGE_STATS)
            window._set_period("all")
            _save_window(window, OUTPUT_DIR / "statistics-light.png")

            themes.set_mode("dark")
            window._set_period("week")
            window._set_page(window.PAGE_REPORTS)
            window._shift_report_period(-1)
            for scroll in window._reports.findChildren(QScrollArea):
                scroll.verticalScrollBar().setValue(0)
            _save_window(window, OUTPUT_DIR / "reports-dark.png")
        finally:
            window.close()
            collector.stop()
            db.close()
    print(f"Screenshots: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
