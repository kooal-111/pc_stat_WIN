from __future__ import annotations

import sys
import time

import psutil
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from pc_stat_win import autostart
from pc_stat_win.branding import app_icon
from pc_stat_win.collector import UsageCollector
from pc_stat_win.config import POLL_INTERVAL_MS, ensure_app_dirs
from pc_stat_win.db import Database
from pc_stat_win.formatting import format_duration_seconds
from pc_stat_win.ui.main_window import MainWindow
from pc_stat_win.ui.styles import load_stylesheet


def _argv_without_background_flag() -> list[str]:
    return [a for a in sys.argv if a != "--background"]


def main() -> int:
    ensure_app_dirs()
    start_to_tray_only = "--background" in sys.argv
    app = QApplication(_argv_without_background_flag())
    app.setApplicationName("PC Stat")
    app.setQuitOnLastWindowClosed(False)

    db_path = ensure_app_dirs()
    db = Database(db_path)
    autostart.refresh_registry_if_stale(db.get_autostart_enabled())
    theme = db.get_setting("ui_theme", "dark") or "dark"
    if theme not in ("dark", "light"):
        theme = "dark"
    app.setStyleSheet(load_stylesheet(theme))

    sh = app.styleHints()
    if hasattr(sh, "setColorScheme"):
        try:
            sh.setColorScheme(
                Qt.ColorScheme.Dark if theme == "dark" else Qt.ColorScheme.Light
            )
        except Exception:
            pass

    icon = app_icon()
    app.setWindowIcon(icon)

    collector = UsageCollector(db, poll_interval_ms=POLL_INTERVAL_MS)
    win = MainWindow(db, collector, window_icon=icon)
    collector.start()

    tray = QSystemTrayIcon(app)
    tray.setIcon(icon)
    tray.setVisible(True)

    menu = QMenu()
    act_show = QAction("Открыть", app)
    act_show.triggered.connect(win.show)
    menu.addAction(act_show)

    act_uptime = QAction(app)
    boot = float(psutil.boot_time())

    def refresh_tray() -> None:
        up = max(0.0, time.time() - boot)
        act_uptime.setText(f"С загрузки Windows: {format_duration_seconds(up)}")

    refresh_tray()
    collector.tick_done.connect(refresh_tray)
    menu.addAction(act_uptime)
    menu.addSeparator()
    act_quit = QAction("Выход", app)

    def on_quit() -> None:
        collector.stop()
        db.close()
        app.quit()

    act_quit.triggered.connect(on_quit)
    menu.addAction(act_quit)
    tray.setContextMenu(menu)

    def tray_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            win.show()
            win.raise_()
            win.activateWindow()

    tray.activated.connect(tray_activated)

    show_window = (not start_to_tray_only) and db.get_show_main_window_on_launch()
    if show_window:
        win.show()
        tray.showMessage(
            "PC Stat",
            "Трекер запущен в фоне.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
    code = app.exec()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
