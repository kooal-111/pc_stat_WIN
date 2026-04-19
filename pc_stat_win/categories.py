from __future__ import annotations

import os
from typing import Final

# Расширенная таксономия (ключи в БД и в коде)
WORK = "work"
DISTRACTION = "distraction"
COMMUNICATION = "communication"
GAMES = "games"
MEDIA = "media"
DEVTOOLS = "devtools"
SYSTEM = "system"
OTHER = "other"

_LEGACY_PRODUCTIVE = "productive"
_LEGACY_UNPRODUCTIVE = "unproductive"
_LEGACY_NEUTRAL = "neutral"

ALL_CATEGORY_KEYS: Final[tuple[str, ...]] = (
    WORK,
    DISTRACTION,
    COMMUNICATION,
    GAMES,
    MEDIA,
    DEVTOOLS,
    SYSTEM,
    OTHER,
)

CATEGORY_LABELS_RU: dict[str, str] = {
    WORK: "Работа / учёба",
    DISTRACTION: "Отвлечения",
    COMMUNICATION: "Общение",
    GAMES: "Игры",
    MEDIA: "Медиа / контент",
    DEVTOOLS: "Разработка / IDE",
    SYSTEM: "Система / утилиты",
    OTHER: "Прочее / нейтрально",
}


def normalize_legacy_category(cat: str) -> str:
    return {
        _LEGACY_PRODUCTIVE: WORK,
        _LEGACY_UNPRODUCTIVE: DISTRACTION,
        _LEGACY_NEUTRAL: OTHER,
    }.get(cat, cat)


_PATH_HINTS: list[tuple[str, str]] = [
    (r"steam\steamapps", GAMES),
    (r"epic games", GAMES),
    (r"riot games", GAMES),
    (r"microsoft office", WORK),
    (r"program files\google\chrome", OTHER),
    (r"program files (x86)\google\chrome", OTHER),
]


def default_category_for_path(exe_path: str) -> str | None:
    p = exe_path.lower().replace("/", "\\")
    for fragment, cat in _PATH_HINTS:
        if fragment in p:
            return cat
    return None


_DEFAULT_BY_BASENAME: dict[str, str] = {
    "telegram.exe": COMMUNICATION,
    "discord.exe": COMMUNICATION,
    "slack.exe": WORK,
    "teams.exe": WORK,
    "zoom.exe": COMMUNICATION,
    "chrome.exe": OTHER,
    "msedge.exe": OTHER,
    "firefox.exe": OTHER,
    "steam.exe": GAMES,
    "epicgameslauncher.exe": GAMES,
    "devenv.exe": DEVTOOLS,
    "code.exe": DEVTOOLS,
    "cursor.exe": DEVTOOLS,
    "pycharm64.exe": DEVTOOLS,
    "windowsterminal.exe": DEVTOOLS,
    "powershell.exe": DEVTOOLS,
    "cmd.exe": SYSTEM,
    "notepad.exe": OTHER,
    "explorer.exe": SYSTEM,
    "spotify.exe": MEDIA,
    "vlc.exe": MEDIA,
}


def default_category_for_basename(basename_lower: str) -> str:
    return _DEFAULT_BY_BASENAME.get(basename_lower, OTHER)


def resolve_default_category(exe_path: str) -> str:
    path_cat = default_category_for_path(exe_path)
    if path_cat is not None:
        return path_cat
    base = os.path.basename(exe_path).lower()
    return default_category_for_basename(base)
