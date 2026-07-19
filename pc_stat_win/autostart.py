from __future__ import annotations

import shutil
import sys
from pathlib import Path

import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_VALUE_NAME = "PCStat"
# Автозагрузка Windows: окно не показываем, трекер и трей работают.
_BACKGROUND_SUFFIX = " --background"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"{_BACKGROUND_SUFFIX}'
    pyw = shutil.which("pythonw") or shutil.which("pythonw.exe")
    if pyw:
        return f'"{Path(pyw).resolve()}" -m pc_stat_win --background'
    return f'"{Path(sys.executable).resolve()}" -m pc_stat_win --background'


def sync_run_key(autostart_should_be_on: bool) -> bool:
    """Make the per-user Run entry match the persisted setting."""
    if autostart_should_be_on:
        expected = launch_command()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
                value, _value_type = winreg.QueryValueEx(key, _APP_VALUE_NAME)
            if str(value) == expected:
                return True
        except OSError:
            pass
    return set_enabled(autostart_should_be_on)


def sync_run_key_if_autostart(autostart_should_be_on: bool) -> bool:
    """Backward-compatible alias for callers from older releases."""
    return sync_run_key(autostart_should_be_on)


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, _APP_VALUE_NAME)
            return bool(str(val).strip())
    except OSError:
        return False


def set_enabled(enabled: bool) -> bool:
    if enabled:
        try:
            key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                _RUN_KEY,
                0,
                winreg.KEY_SET_VALUE,
            )
        except OSError:
            return False
        with key:
            try:
                winreg.SetValueEx(
                    key,
                    _APP_VALUE_NAME,
                    0,
                    winreg.REG_SZ,
                    launch_command(),
                )
            except OSError:
                return False
        return True

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            _RUN_KEY,
            0,
            winreg.KEY_SET_VALUE,
        )
    except FileNotFoundError:
        return True
    except OSError:
        return False
    with key:
        try:
            winreg.DeleteValue(key, _APP_VALUE_NAME)
        except FileNotFoundError:
            return True
        except OSError:
            return False
    return True
