from __future__ import annotations

import ctypes
import platform
import sys
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget

_WINDOWS_11_MICA_BUILD = 22621
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMSBT_MAINWINDOW = 2


class WindowMaterial(str, Enum):
    SOLID = "solid"
    MICA = "mica"


def windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        return int(sys.getwindowsversion().build)
    except (AttributeError, ValueError):
        try:
            return int(platform.version().split(".")[-1])
        except (ValueError, IndexError):
            return 0


def mica_supported() -> bool:
    return sys.platform == "win32" and windows_build() >= _WINDOWS_11_MICA_BUILD


def _set_window_property(window: QWidget, material: WindowMaterial) -> None:
    if window.property("windowMaterial") == material.value:
        return
    window.setProperty("windowMaterial", material.value)
    style = window.style()
    style.unpolish(window)
    style.polish(window)
    window.update()


def _solid_fallback(window: QWidget) -> WindowMaterial:
    _set_window_property(window, WindowMaterial.SOLID)
    return WindowMaterial.SOLID


def apply_window_material(window: QWidget, *, dark: bool) -> WindowMaterial:
    """Apply Windows 11 Mica while preserving Qt's native window frame."""
    if window.windowFlags() & Qt.WindowType.FramelessWindowHint:
        return _solid_fallback(window)
    if not mica_supported():
        return _solid_fallback(window)

    try:
        hwnd = int(window.winId())
        dwmapi = ctypes.WinDLL("dwmapi")

        dark_value = ctypes.c_int(1 if dark else 0)
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            _DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark_value),
            ctypes.sizeof(dark_value),
        )

        backdrop = ctypes.c_int(_DWMSBT_MAINWINDOW)
        result = dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd),
            _DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(backdrop),
            ctypes.sizeof(backdrop),
        )
        if int(result) != 0:
            return _solid_fallback(window)
    except (AttributeError, OSError, TypeError, ValueError):
        return _solid_fallback(window)

    _set_window_property(window, WindowMaterial.MICA)
    return WindowMaterial.MICA
