from __future__ import annotations

import ctypes
from ctypes import wintypes


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def idle_seconds() -> float:
    """Seconds since last keyboard or mouse input (same tick domain as GetTickCount)."""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    tick_now = ctypes.windll.kernel32.GetTickCount()
    idle_ms = (tick_now - lii.dwTime) & 0xFFFFFFFF
    return idle_ms / 1000.0
