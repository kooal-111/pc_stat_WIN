from __future__ import annotations

import sys
import time

import psutil
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMessageBox, QMenu, QSystemTrayIcon

from pc_stat_win import autostart
from pc_stat_win.branding import app_icon
from pc_stat_win.collector import UsageCollector
from pc_stat_win.config import POLL_INTERVAL_MS, ensure_app_dirs
from pc_stat_win.db import Database
from pc_stat_win.formatting import format_duration_seconds
from pc_stat_win.single_instance import SingleInstance
from pc_stat_win.ui.main_window import MainWindow
from pc_stat_win.ui.styles import load_stylesheet
from pc_stat_win.version import APP_VERSION


def _argv_without_background_flag() -> list[str]:
    return [a for a in sys.argv if a != "--background"]


def _seconds_since_boot() -> float:
    try:
        return max(0.0, time.time() - float(psutil.boot_time()))
    except Exception:
        return 1e9


def main() -> int:
    ensure_app_dirs()
    db_path = ensure_app_dirs()
    app = QApplication(_argv_without_background_flag())
    app.setApplicationName("PC Stat")
    app.setApplicationVersion(APP_VERSION)

    instance = SingleInstance()
    if instance.already_running:
        QMessageBox.information(
            None,
            "PC Stat",
            "PC Stat уже запущен. Откройте окно через значок в области уведомлений.",
        )
        instance.close()
        return 0

    db = Database(db_path)
    autostart.sync_run_key_if_autostart(db.get_autostart_enabled())
    start_to_tray_only = "--background" in sys.argv
    tray_available = QSystemTrayIcon.isSystemTrayAvailable()
    app.setQuitOnLastWindowClosed(not tray_available)
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
    win = MainWindow(db, collector, window_icon=icon, tray_available=tray_available)
    collector.start()

    tray: QSystemTrayIcon | None = None

    if tray_available:
        tray = QSystemTrayIcon(app)
        tray.setIcon(icon)
        tray.setVisible(True)

        menu = QMenu()
        act_show = QAction("Открыть", app)
        act_show.triggered.connect(win.show)
        menu.addAction(act_show)

        act_uptime = QAction(app)
        menu.addAction(act_uptime)
        menu.addSeparator()
        act_quit = QAction("Выход", app)
        menu.addAction(act_quit)
        tray.setContextMenu(menu)
    else:
        act_uptime = QAction(app)
        act_quit = QAction("Выход", app)
    boot = float(psutil.boot_time())

    def refresh_tray() -> None:
        up = max(0.0, time.time() - boot)
        act_uptime.setText(f"С загрузки Windows: {format_duration_seconds(up)}")

    refresh_tray()
    collector.tick_done.connect(refresh_tray)

    closed = False
    def on_quit() -> None:
        nonlocal closed
        if closed:
            return
        closed = True
        collector.stop()
        db.optimize()
        db.close()
        instance.close()
        app.quit()

    act_quit.triggered.connect(on_quit)
    app.aboutToQuit.connect(on_quit)

    def tray_activated(reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            win.show()
            win.raise_()
            win.activateWindow()

    if tray is not None:
        tray.activated.connect(tray_activated)

    show_window = (not tray_available) or (
        (not start_to_tray_only) and db.get_show_main_window_on_launch()
    )
    if show_window:
        win.show()
        if tray is not None:
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
