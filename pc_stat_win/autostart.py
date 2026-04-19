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


def sync_run_key_if_autostart(autostart_should_be_on: bool) -> bool:
    """Если автозагрузка включена — всегда перезаписать HKCU\\...\\Run актуальной командой (путь к exe и --background).

    Возвращает True, если до записи в реестре не было `--background` (тот же запуск ещё без флага в argv).
    """
    if not autostart_should_be_on:
        return False
    was_stale = True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, _APP_VALUE_NAME)
        was_stale = "--background" not in str(val).lower()
    except OSError:
        was_stale = True
    set_enabled(True)
    return was_stale


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
