from __future__ import annotations

import os
import time
from collections import OrderedDict
from dataclasses import dataclass

import psutil
import win32gui
import win32process

from pc_stat_win.config import FOREGROUND_CACHE_MAX_SIZE, FOREGROUND_CACHE_TTL_SECONDS


@dataclass(frozen=True, slots=True)
class ForegroundInfo:
    hwnd: int
    pid: int
    exe_path: str
    exe_name: str
    window_title: str


_ProcessIdentity = tuple[str, str]
_ProcessKey = tuple[int, int]
_PROCESS_CACHE: OrderedDict[_ProcessKey, tuple[float, _ProcessIdentity]] = OrderedDict()


def _norm_path(p: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(p))
    except OSError:
        return p


def _process_identity(pid: int, hwnd: int, now: float) -> _ProcessIdentity | None:
    # A foreground HWND changes when Windows reuses a recently exited PID.
    key = (pid, hwnd)
    cached = _PROCESS_CACHE.get(key)
    if cached is not None:
        expires_at, identity = cached
        if expires_at > now:
            _PROCESS_CACHE.move_to_end(key)
            return identity
        del _PROCESS_CACHE[key]

    try:
        exe = psutil.Process(pid).exe()
    except (psutil.Error, OSError):
        return None

    exe_path = _norm_path(exe)
    identity = (exe_path, os.path.basename(exe_path).lower())
    _PROCESS_CACHE[key] = (now + FOREGROUND_CACHE_TTL_SECONDS, identity)
    _PROCESS_CACHE.move_to_end(key)
    while len(_PROCESS_CACHE) > FOREGROUND_CACHE_MAX_SIZE:
        _PROCESS_CACHE.popitem(last=False)
    return identity


def get_foreground_app(*, monotonic_clock=time.monotonic) -> ForegroundInfo | None:
    try:
        hwnd = win32gui.GetForegroundWindow()
    except win32gui.error:
        return None
    if not hwnd:
        return None
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except win32process.error:
        return None
    if pid <= 0:
        return None
    try:
        title = win32gui.GetWindowText(hwnd) or ""
    except win32gui.error:
        title = ""
    identity = _process_identity(int(pid), int(hwnd), monotonic_clock())
    if identity is None:
        return None
    exe_path, exe_name = identity
    return ForegroundInfo(
        hwnd=int(hwnd),
        pid=int(pid),
        exe_path=exe_path,
        exe_name=exe_name,
        window_title=title,
    )
