from __future__ import annotations

import os
from dataclasses import dataclass

import psutil
import win32gui
import win32process


@dataclass(frozen=True, slots=True)
class ForegroundInfo:
    hwnd: int
    pid: int
    exe_path: str
    exe_name: str
    window_title: str


def _norm_path(p: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(p))
    except OSError:
        return p


def get_foreground_app() -> ForegroundInfo | None:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except win32process.error:
        return None
    if pid <= 0:
        return None
    title = win32gui.GetWindowText(hwnd) or ""
    try:
        proc = psutil.Process(pid)
        exe = proc.exe()
    except (psutil.Error, OSError):
        return None
    exe_path = _norm_path(exe)
    exe_name = os.path.basename(exe_path)
    return ForegroundInfo(
        hwnd=int(hwnd),
        pid=int(pid),
        exe_path=exe_path,
        exe_name=exe_name.lower(),
        window_title=title,
    )
