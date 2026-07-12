from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace

import psutil
from PySide6.QtCore import QObject, QTimer, Signal

from pc_stat_win.config import (
    COLLECTOR_FLUSH_INTERVAL_SECONDS,
    MAX_TICK_INTERVAL_MS,
)
from pc_stat_win.db import BufferedInterval, Database
from pc_stat_win.foreground import ForegroundInfo, get_foreground_app
from pc_stat_win.idle import idle_seconds
from pc_stat_win.process_filter import should_track_foreground


class IdleUnavailableError(RuntimeError):
    pass


class UsageCollector(QObject):
    """Poll foreground activity and persist bounded, monotonic intervals."""

    tick_done = Signal()
    error_occurred = Signal(str)
    recovered = Signal()

    def __init__(
        self,
        db: Database,
        poll_interval_ms: int = 2000,
        *,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
        foreground_provider: Callable[[], ForegroundInfo | None] = get_foreground_app,
        idle_provider: Callable[[], float | None] = idle_seconds,
        boot_time_provider: Callable[[], float] = psutil.boot_time,
    ) -> None:
        super().__init__()
        self._db = db
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._foreground_provider = foreground_provider
        self._idle_provider = idle_provider

        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._on_tick)

        now_mono = self._monotonic_clock()
        self._last_monotonic = now_mono
        self._last_wall = self._wall_clock()
        self._last_flush_monotonic = now_mono
        self._pc_interval: BufferedInterval | None = None
        self._app_interval: BufferedInterval | None = None
        self._app_key: tuple[str, str] | None = None
        self._in_error = False

        self.reload_settings()
        self._db.log_boot_if_new(float(boot_time_provider()))

    @property
    def _pc_row_id(self) -> int | None:
        return None if self._pc_interval is None else self._pc_interval.row_id

    @property
    def _app_row_id(self) -> int | None:
        return None if self._app_interval is None else self._app_interval.row_id

    def reload_settings(self) -> None:
        """Refresh settings once; ticks use this cache without querying SQLite."""
        self._afk_seconds = self._db.get_afk_seconds()
        self._excluded_exes = self._db.get_excluded_exes()

    def start(self) -> None:
        now_mono = self._monotonic_clock()
        self._last_monotonic = now_mono
        self._last_wall = self._wall_clock()
        self._last_flush_monotonic = now_mono
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        if self.flush("shutdown"):
            self._clear_open_state()

    def flush(self, reason: str = "manual") -> bool:
        """Persist buffered intervals without exposing collector internals."""
        del reason
        try:
            self._flush(self._monotonic_clock())
        except Exception as exc:
            self._report_error(exc)
            return False
        self._report_recovered()
        return True

    def _on_tick(self) -> None:
        try:
            self._tick()
        except Exception as exc:
            self._report_error(exc)
        else:
            self._report_recovered()
        finally:
            self.tick_done.emit()

    def _tick(self) -> None:
        now_mono = self._monotonic_clock()
        now_wall = self._wall_clock()
        elapsed_mono = max(0.0, now_mono - self._last_monotonic)
        elapsed_wall = now_wall - self._last_wall
        dt_ms = elapsed_mono * 1000.0
        self._last_monotonic = now_mono
        self._last_wall = now_wall

        clock_shifted = abs(elapsed_wall - elapsed_mono) > 5.0
        if dt_ms > MAX_TICK_INTERVAL_MS or clock_shifted:
            self._flush(now_mono)
            self._clear_open_state()
            return

        idle_sec = self._idle_provider()
        if idle_sec is None:
            self._flush(now_mono)
            self._clear_open_state()
            raise IdleUnavailableError("Windows idle-time query failed")
        if idle_sec >= self._afk_seconds:
            self._flush(now_mono)
            self._clear_open_state()
            return

        duration_ms = int(round(dt_ms))
        if duration_ms <= 0:
            return

        foreground = self._foreground_provider()
        tracked = (
            foreground
            if foreground is not None
            and should_track_foreground(
                foreground.exe_path,
                foreground.exe_name,
                self._excluded_exes,
            )
            else None
        )
        next_key = (
            (tracked.exe_path, tracked.exe_name) if tracked is not None else None
        )

        if self._app_interval is not None and next_key != self._app_key:
            self._flush(now_mono)
            self._app_interval = None
            self._app_key = None

        self._extend_pc(now_wall, duration_ms)
        self._extend_app(now_wall, duration_ms, tracked)

        if now_mono - self._last_flush_monotonic >= COLLECTOR_FLUSH_INTERVAL_SECONDS:
            self._flush(now_mono)

    def _extend_pc(self, now_wall: float, duration_ms: int) -> None:
        if self._pc_interval is None:
            start_ts = now_wall - duration_ms / 1000.0
            self._pc_interval = BufferedInterval(
                kind="pc_active",
                start_ts=start_ts,
                end_ts=now_wall,
                duration_ms=duration_ms,
            )
            return
        total_ms = self._pc_interval.duration_ms + duration_ms
        self._pc_interval = replace(
            self._pc_interval,
            end_ts=self._pc_interval.start_ts + total_ms / 1000.0,
            duration_ms=total_ms,
        )

    def _extend_app(
        self,
        now_wall: float,
        duration_ms: int,
        foreground: ForegroundInfo | None,
    ) -> None:
        if foreground is None:
            return
        if self._app_interval is None:
            self._app_key = (foreground.exe_path, foreground.exe_name)
            start_ts = now_wall - duration_ms / 1000.0
            self._app_interval = BufferedInterval(
                kind="app",
                start_ts=start_ts,
                end_ts=now_wall,
                duration_ms=duration_ms,
                exe_path=foreground.exe_path,
                exe_name=foreground.exe_name,
                window_title=foreground.window_title or None,
            )
            return
        total_ms = self._app_interval.duration_ms + duration_ms
        self._app_interval = replace(
            self._app_interval,
            end_ts=self._app_interval.start_ts + total_ms / 1000.0,
            duration_ms=total_ms,
            window_title=foreground.window_title
            or self._app_interval.window_title,
        )

    def _flush(self, now_mono: float) -> None:
        if self._pc_interval is None and self._app_interval is None:
            self._last_flush_monotonic = now_mono
            return

        result = self._db.persist_usage(self._pc_interval, self._app_interval)
        if self._pc_interval is not None and result.pc_row_id is None:
            raise RuntimeError("database did not return the persisted PC interval id")
        if self._app_interval is not None and result.app_row_id is None:
            raise RuntimeError("database did not return the persisted app interval id")

        if self._pc_interval is not None:
            self._pc_interval = replace(
                self._pc_interval, row_id=result.pc_row_id
            )
        if self._app_interval is not None:
            self._app_interval = replace(
                self._app_interval, row_id=result.app_row_id
            )
        self._last_flush_monotonic = now_mono

    def _clear_open_state(self) -> None:
        self._pc_interval = None
        self._app_interval = None
        self._app_key = None

    def _report_error(self, exc: Exception) -> None:
        if not self._in_error:
            self._in_error = True
            self.error_occurred.emit(str(exc))

    def _report_recovered(self) -> None:
        if self._in_error:
            self._in_error = False
            self.recovered.emit()
