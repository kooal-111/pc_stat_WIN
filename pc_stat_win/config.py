from __future__ import annotations

import os
from pathlib import Path


def _local_app_data() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base)
    return Path.home() / "AppData" / "Local"


APP_DIR_NAME = "pc_stat_win"
DEFAULT_AFK_SECONDS = 120.0
POLL_INTERVAL_MS = 2000
MAX_TICK_INTERVAL_MS = 15000
UI_REFRESH_INTERVAL_MS = 10000

# Foreground exe basename — usually not focused for user work; still filter conservative
SYSTEM32_SILENT_EXES = frozenset(
    name.lower()
    for name in {
        "svchost.exe",
        "dwm.exe",
        "csrss.exe",
        "smss.exe",
        "wininit.exe",
        "services.exe",
        "lsass.exe",
        "fontdrvhost.exe",
        "sihost.exe",
        "taskhostw.exe",
        "AggregatorHost.exe",
        "RuntimeBroker.exe",
        "dllhost.exe",
        "MoUsoCoreWorker.exe",
        "SecurityHealthSystray.exe",
        "SearchHost.exe",
        "ShellExperienceHost.exe",
        "StartMenuExperienceHost.exe",
        "SystemSettings.exe",
        "TextInputHost.exe",
        "ctfmon.exe",
    }
)


def default_db_path() -> Path:
    return _local_app_data() / APP_DIR_NAME / "data.sqlite"


def ensure_app_dirs(db_path: Path | None = None) -> Path:
    path = db_path or default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
