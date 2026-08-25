from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from inspect import Parameter, signature

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
        foreground_provider: Callable[..., ForegroundInfo | None] = get_foreground_app,
        idle_provider: Callable[[], float | None] = idle_seconds,
        boot_time_provider: Callable[[], float] = psutil.boot_time,
        stop_retry_attempts: int = 3,
        retry_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__()
        self._db = db
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._foreground_provider = foreground_provider
        self._foreground_accepts_title_flag = (
            self._provider_accepts_include_window_title(foreground_provider)
        )
        self._idle_provider = idle_provider
        self._stop_retry_attempts = max(1, int(stop_retry_attempts))
        self._retry_sleep = retry_sleep

        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._on_tick)

        now_mono = self._monotonic_clock()
        self._last_monotonic = now_mono
        self._last_wall = self._wall_clock()
        self._last_flush_monotonic = now_mono
        self._pending_intervals: list[BufferedInterval] = []
        self._pc_interval: BufferedInterval | None = None
        self._app_interval: BufferedInterval | None = None
        self._app_key: tuple[str, str] | None = None
        self._in_error = False

        self.reload_settings()
        self._boot_ts = float(boot_time_provider())
        self._db.log_boot_if_new(self._boot_ts, self._last_wall)

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
        self._collect_window_titles = self._db.get_collect_window_titles()
        if not self._collect_window_titles:
            self._pending_intervals = [
                replace(interval, window_title=None)
                if interval.kind == "app" and interval.window_title is not None
                else interval
                for interval in self._pending_intervals
            ]
            if self._app_interval is not None:
                self._app_interval = replace(
                    self._app_interval, window_title=None
                )

    def start(self) -> None:
        now_mono = self._monotonic_clock()
        self._last_monotonic = now_mono
        self._last_wall = self._wall_clock()
        self._last_flush_monotonic = now_mono
        self._timer.start()

    def live_intervals_snapshot(self) -> tuple[BufferedInterval, ...]:
        """Return unflushed intervals so UI stats can stay live without a DB write."""
        intervals = list(self._pending_intervals)
        if self._pc_interval is not None:
            intervals.append(self._pc_interval)
        if self._app_interval is not None:
            intervals.append(self._app_interval)
        return tuple(intervals)

    def stop(self) -> bool:
        self._timer.stop()
        self._complete_open_intervals()

        flush_ok = False
        for attempt in range(self._stop_retry_attempts):
            if self.flush("shutdown"):
                flush_ok = True
                break
            if attempt + 1 < self._stop_retry_attempts:
                self._retry_sleep(0.05)

        touch_ok = False
        for attempt in range(self._stop_retry_attempts):
            try:
                touch_ok = self._db.touch_boot(
                    self._boot_ts, self._wall_clock()
                )
                if not touch_ok:
                    raise LookupError("current boot session is missing")
            except Exception as exc:
                self._report_error(exc)
                if attempt + 1 < self._stop_retry_attempts:
                    self._retry_sleep(0.05)
                continue
            break

        if flush_ok and touch_ok:
            self._report_recovered()
        return flush_ok and touch_ok

    def flush(self, reason: str = "manual") -> bool:
        """Persist buffered intervals without exposing collector internals."""
        try:
            self._flush(self._monotonic_clock())
        except Exception as exc:
            self._report_error(RuntimeError(f"{reason} flush failed: {exc}"))
            return False
        self._report_recovered()
        return True

    def clear_history(self) -> int:
        """Discard buffered usage and securely clear persisted statistics."""
        was_active = self._timer.isActive()
        self._timer.stop()
        try:
            self._pending_intervals.clear()
            self._clear_open_state()
            deleted = self._db.delete_all_history()
            now_mono = self._monotonic_clock()
            now_wall = self._wall_clock()
            self._last_monotonic = now_mono
            self._last_wall = now_wall
            self._last_flush_monotonic = now_mono
            self._db.log_boot_if_new(self._boot_ts, now_wall)
            self._report_recovered()
            return deleted
        except Exception as exc:
            self._report_error(exc)
            raise
        finally:
            if was_active:
                self._timer.start()

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
            self._complete_open_intervals()
            self._flush(now_mono)
            return

        idle_sec = self._idle_provider()
        if idle_sec is None:
            self._complete_open_intervals()
            self._flush(now_mono)
            raise IdleUnavailableError("Windows idle-time query failed")
        if idle_sec >= self._afk_seconds:
            self._complete_open_intervals()
            self._flush(now_mono)
            return

        duration_ms = int(round(dt_ms))
        if duration_ms <= 0:
            return

        foreground = self._current_foreground()
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

        self._extend_pc(now_wall, duration_ms)
        if self._app_interval is not None and next_key != self._app_key:
            self._pending_intervals.append(self._app_interval)
            self._app_interval = None
            self._app_key = None
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
                window_title=(
                    foreground.window_title or None
                    if self._collect_window_titles
                    else None
                ),
            )
            return
        total_ms = self._app_interval.duration_ms + duration_ms
        self._app_interval = replace(
            self._app_interval,
            end_ts=self._app_interval.start_ts + total_ms / 1000.0,
            duration_ms=total_ms,
            window_title=(
                foreground.window_title or self._app_interval.window_title
                if self._collect_window_titles
                else None
            ),
        )

    def _flush(self, now_mono: float) -> None:
        batch = list(self._pending_intervals)
        pc_index: int | None = None
        app_index: int | None = None
        if self._pc_interval is not None:
            pc_index = len(batch)
            batch.append(self._pc_interval)
        if self._app_interval is not None:
            app_index = len(batch)
            batch.append(self._app_interval)

        if not batch:
            self._last_flush_monotonic = now_mono
            return

        row_ids = self._db.persist_usage(batch)
        if not isinstance(row_ids, list) or len(row_ids) != len(batch):
            raise RuntimeError("database returned an invalid persisted ID sequence")

        if pc_index is not None and self._pc_interval is not None:
            self._pc_interval = replace(
                self._pc_interval, row_id=row_ids[pc_index]
            )
        if app_index is not None and self._app_interval is not None:
            self._app_interval = replace(
                self._app_interval, row_id=row_ids[app_index]
            )
        self._pending_intervals.clear()
        self._last_flush_monotonic = now_mono

    @staticmethod
    def _provider_accepts_include_window_title(
        provider: Callable[..., ForegroundInfo | None],
    ) -> bool:
        try:
            parameters = signature(provider).parameters.values()
        except (TypeError, ValueError):
            return False
        return any(
            parameter.kind == Parameter.VAR_KEYWORD
            or parameter.name == "include_window_title"
            for parameter in parameters
        )

    def _current_foreground(self) -> ForegroundInfo | None:
        if self._foreground_accepts_title_flag:
            return self._foreground_provider(
                include_window_title=self._collect_window_titles
            )
        return self._foreground_provider()

    def _complete_open_intervals(self) -> None:
        if self._pc_interval is not None:
            self._pending_intervals.append(self._pc_interval)
        if self._app_interval is not None:
            self._pending_intervals.append(self._app_interval)
        self._clear_open_state()

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
