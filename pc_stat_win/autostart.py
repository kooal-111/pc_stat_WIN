from __future__ import annotations

import shutil
import sys
from pathlib import Path

import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_VALUE_NAME = "PCStat"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    pyw = shutil.which("pythonw") or shutil.which("pythonw.exe")
    if pyw:
        return f'"{Path(pyw).resolve()}" -m pc_stat_win'
    return f'"{Path(sys.executable).resolve()}" -m pc_stat_win'


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, _APP_VALUE_NAME)
            return bool(str(val).strip())
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, _APP_VALUE_NAME, 0, winreg.REG_SZ, launch_command())
        else:
            try:
                winreg.DeleteValue(k, _APP_VALUE_NAME)
            except OSError:
                pass
