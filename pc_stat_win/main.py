from __future__ import annotations

import logging
import os
import sys
import time
from typing import TYPE_CHECKING

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMessageBox, QMenu, QSystemTrayIcon

from pc_stat_win import autostart
from pc_stat_win.branding import app_icon
from pc_stat_win.collector import UsageCollector
from pc_stat_win.config import POLL_INTERVAL_MS, ensure_app_dirs
from pc_stat_win.db import Database
from pc_stat_win.formatting import format_duration_seconds
from pc_stat_win.logging_config import configure_logging
from pc_stat_win.single_instance import DEFAULT_MUTEX_NAME, DEFAULT_SERVER_NAME, SingleInstance
from pc_stat_win.version import APP_VERSION

if TYPE_CHECKING:
    from pc_stat_win.ui.main_window import MainWindow
    from pc_stat_win.ui.theme_manager import ThemeManager


LOGGER = logging.getLogger(__name__)


def _argv_without_background_flag() -> list[str]:
    internal_flags = {"--background", "--smoke-test"}
    return [argument for argument in sys.argv if argument not in internal_flags]


def _install_exception_hook() -> None:
    previous_hook = sys.excepthook

    def handle_exception(exc_type: type[BaseException], exc: BaseException, trace: object) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            previous_hook(exc_type, exc, trace)
            return
        LOGGER.critical("Unhandled exception", exc_info=(exc_type, exc, trace))

    sys.excepthook = handle_exception


def main() -> int:
    db_path = ensure_app_dirs()
    configure_logging()
    _install_exception_hook()

    app = QApplication(_argv_without_background_flag())
    app.setApplicationName("PC Stat")
    app.setApplicationDisplayName("PC Stat")
    app.setApplicationVersion(APP_VERSION)
    smoke_test = "--smoke-test" in sys.argv

    window: MainWindow | None = None
    theme_manager: ThemeManager | None = None
    db: Database | None = None
    collector: UsageCollector | None = None
    instance: SingleInstance | None = None
    tray: QSystemTrayIcon | None = None
    shutting_down = False
    tray_available = QSystemTrayIcon.isSystemTrayAvailable() and not smoke_test
    start_to_tray_only = "--background" in sys.argv

    def cleanup() -> None:
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        if collector is not None:
            try:
                if collector.stop() is False:
                    LOGGER.critical("Collector could not persist all pending usage during shutdown")
            except Exception:
                LOGGER.exception("Collector shutdown failed")
        if db is not None:
            try:
                db.close()
            except Exception:
                LOGGER.exception("Database shutdown failed")
        if instance is not None:
            instance.close()

    def window_destroyed(_object: object | None = None) -> None:
        nonlocal window
        window = None

    def handle_theme_change(resolved: str) -> None:
        if window is not None:
            window.apply_theme(resolved)

    def ensure_theme_manager() -> ThemeManager:
        nonlocal theme_manager
        if theme_manager is None:
            from pc_stat_win.ui.theme_manager import ThemeManager

            assert db is not None
            theme_mode = db.get_setting("ui_theme", "system") or "system"
            if theme_mode not in ("system", "dark", "light"):
                theme_mode = "system"
            theme_manager = ThemeManager(app, theme_mode, app)
            theme_manager.theme_changed.connect(handle_theme_change)
        return theme_manager

    def show_window() -> None:
        nonlocal window
        assert db is not None and collector is not None
        manager = ensure_theme_manager()
        if window is None:
            from pc_stat_win.ui.main_window import MainWindow

            window = MainWindow(
                db,
                collector,
                window_icon=icon,
                tray_available=tray_available,
            )
            manager.register_window(window)
            window.theme_changed.connect(manager.set_mode)
            if hasattr(window, "quit_requested"):
                window.quit_requested.connect(app.quit)
            window.destroyed.connect(window_destroyed)
            window.apply_theme(manager.resolved_theme)
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()

    smoke_suffix = f".Smoke.{os.getpid()}" if smoke_test else ""
    try:
        instance = SingleInstance(
            name=f"{DEFAULT_MUTEX_NAME}{smoke_suffix}",
            server_name=f"{DEFAULT_SERVER_NAME}{smoke_suffix}",
            on_show=show_window,
        )
    except OSError as exc:
        LOGGER.exception("Unable to create the single-instance guard")
        QMessageBox.critical(None, "PC Stat", f"Не удалось запустить защиту одного экземпляра.\n\n{exc}")
        return 1
    if instance.already_running:
        if not instance.activation_sent:
            QMessageBox.information(
                None,
                "PC Stat",
                "PC Stat уже запущен для этой учётной записи Windows.",
            )
        instance.close()
        return 0

    try:
        db = Database(db_path)
        if not autostart.sync_run_key(db.get_autostart_enabled()):
            LOGGER.warning("Unable to synchronize the Windows autostart entry")

        app.setQuitOnLastWindowClosed(not tray_available)
        icon = app_icon()
        app.setWindowIcon(icon)
        boot_time = float(psutil.boot_time())
        collector = UsageCollector(
            db,
            poll_interval_ms=POLL_INTERVAL_MS,
            boot_time_provider=lambda: boot_time,
        )
        collector.start()

        menu = QMenu()
        action_show = QAction("Открыть", app)
        action_show.triggered.connect(show_window)
        menu.addAction(action_show)
        action_uptime = QAction(app)
        action_uptime.setEnabled(False)
        menu.addAction(action_uptime)
        menu.addSeparator()
        action_quit = QAction("Выход", app)
        action_quit.triggered.connect(app.quit)
        menu.addAction(action_quit)

        def refresh_tray_menu() -> None:
            uptime = max(0.0, time.time() - boot_time)
            action_uptime.setText(f"С загрузки Windows: {format_duration_seconds(uptime)}")

        menu.aboutToShow.connect(refresh_tray_menu)
        refresh_tray_menu()

        if tray_available:
            tray = QSystemTrayIcon(app)
            tray.setIcon(icon)
            tray.setToolTip("PC Stat — сбор активности")
            tray.setContextMenu(menu)
            tray.activated.connect(
                lambda reason: show_window()
                if reason
                in (
                    QSystemTrayIcon.ActivationReason.DoubleClick,
                    QSystemTrayIcon.ActivationReason.Trigger,
                )
                else None
            )
            tray.show()
        elif start_to_tray_only:
            LOGGER.warning("System tray is unavailable; background collector remains headless")

        def collector_failed(message: str) -> None:
            LOGGER.warning("Collector temporarily failed: %s", message)
            if tray is not None:
                tray.showMessage(
                    "PC Stat",
                    "Сбор временно приостановлен. Приложение повторит попытку автоматически.",
                    QSystemTrayIcon.MessageIcon.Warning,
                    4000,
                )

        collector.error_occurred.connect(collector_failed)
        collector.recovered.connect(lambda: LOGGER.info("Collector recovered"))
        app.aboutToQuit.connect(cleanup)

        def optimize_database() -> None:
            if shutting_down or db is None:
                return
            try:
                db.optimize()
            except Exception:
                LOGGER.warning("PRAGMA optimize failed", exc_info=True)

        QTimer.singleShot(30_000, optimize_database)

        should_show = smoke_test or (
            not start_to_tray_only
            and ((not tray_available) or db.get_show_main_window_on_launch())
        )
        if should_show:
            show_window()
        if smoke_test:
            QTimer.singleShot(1500, app.quit)
        return int(app.exec())
    except Exception as exc:
        LOGGER.exception("PC Stat startup failed")
        QMessageBox.critical(
            None,
            "PC Stat",
            f"Не удалось запустить приложение.\n\nБаза данных: {db_path}\n\n{exc}",
        )
        return 1
    finally:
        cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
