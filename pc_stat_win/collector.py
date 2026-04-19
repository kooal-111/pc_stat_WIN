from __future__ import annotations

import time

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from pc_stat_win.db import Database
from pc_stat_win.foreground import ForegroundInfo, get_foreground_app
from pc_stat_win.idle import idle_seconds
from pc_stat_win.process_filter import should_track_foreground


class UsageCollector(QObject):
    """Polls foreground + idle; writes merged intervals to SQLite."""

    tick_done = Signal()

    def __init__(self, db: Database, poll_interval_ms: int = 2000) -> None:
        super().__init__()
        self._db = db
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._on_tick)

        self._last_ts = time.time()
        self._pc_row_id: int | None = None
        self._pc_duration_ms = 0
        self._pc_start_ts = 0.0

        self._app_row_id: int | None = None
        self._app_duration_ms = 0
        self._app_start_ts = 0.0
        self._app_key: tuple[str, str] | None = None

        boot = float(psutil.boot_time())
        self._db.log_boot_if_new(boot)

    def start(self) -> None:
        self._last_ts = time.time()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _on_tick(self) -> None:
        now = time.time()
        dt_ms = max(0.0, (now - self._last_ts) * 1000)
        self._last_ts = now

        idle_sec = idle_seconds()
        afk_after = self._db.get_afk_seconds()
        is_afk = idle_sec >= afk_after
        extra_ex = self._db.get_excluded_exes()

        if is_afk:
            self._clear_open_state()
            self.tick_done.emit()
            return

        di = int(round(dt_ms))
        if di <= 0:
            self.tick_done.emit()
            return

        self._extend_pc(now, di)
        fg = get_foreground_app()
        self._extend_app(now, di, fg, extra_ex)
        self.tick_done.emit()

    def _clear_open_state(self) -> None:
        self._pc_row_id = None
        self._pc_duration_ms = 0
        self._app_row_id = None
        self._app_duration_ms = 0
        self._app_key = None

    def _extend_pc(self, now: float, di: int) -> None:
        if self._pc_row_id is None:
            self._pc_start_ts = now - di / 1000.0
            self._pc_duration_ms = di
            self._pc_row_id = self._db.insert_interval(
                "pc_active",
                exe_path=None,
                exe_name=None,
                window_title=None,
                start_ts=self._pc_start_ts,
                end_ts=now,
                duration_ms=self._pc_duration_ms,
            )
        else:
            self._pc_duration_ms += di
            self._db.update_interval(self._pc_row_id, now, self._pc_duration_ms)

    def _extend_app(self, now: float, di: int, fg: ForegroundInfo | None, extra: frozenset[str]) -> None:
        if fg is None or not should_track_foreground(fg.exe_path, fg.exe_name, extra):
            self._app_row_id = None
            self._app_duration_ms = 0
            self._app_key = None
            return

        key: tuple[str, str] = (fg.exe_path, fg.exe_name)
        title = fg.window_title

        if self._app_row_id is None or key != self._app_key:
            self._app_key = key
            self._app_start_ts = now - di / 1000.0
            self._app_duration_ms = di
            self._app_row_id = self._db.insert_interval(
                "app",
                exe_path=fg.exe_path,
                exe_name=fg.exe_name,
                window_title=title or None,
                start_ts=self._app_start_ts,
                end_ts=now,
                duration_ms=self._app_duration_ms,
            )
        else:
            self._app_duration_ms += di
            self._db.update_interval(self._app_row_id, now, self._app_duration_ms)
            if title:
                self._db.update_window_title(self._app_row_id, title)
