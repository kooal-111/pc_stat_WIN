from __future__ import annotations

import os

PRODUCTIVE = "productive"
UNPRODUCTIVE = "unproductive"
NEUTRAL = "neutral"

CATEGORY_LABELS_RU = {
    PRODUCTIVE: "Работа / продуктивно",
    UNPRODUCTIVE: "Отвлечения",
    NEUTRAL: "Нейтрально",
}

# Только низкорисковые эвристики по basename; спорное — neutral
_DEFAULT_BY_BASENAME: dict[str, str] = {
    # соцсети / мессенджеры (часто отвлечение)
    "telegram.exe": UNPRODUCTIVE,
    "discord.exe": NEUTRAL,
    "slack.exe": PRODUCTIVE,
    "teams.exe": PRODUCTIVE,
    "zoom.exe": NEUTRAL,
    "chrome.exe": NEUTRAL,
    "msedge.exe": NEUTRAL,
    "firefox.exe": NEUTRAL,
    # игры
    "steam.exe": UNPRODUCTIVE,
    "epicgameslauncher.exe": UNPRODUCTIVE,
    # dev
    "devenv.exe": PRODUCTIVE,
    "code.exe": PRODUCTIVE,
    "cursor.exe": PRODUCTIVE,
    "pycharm64.exe": PRODUCTIVE,
    "windowsterminal.exe": PRODUCTIVE,
    "powershell.exe": PRODUCTIVE,
    "cmd.exe": NEUTRAL,
    "notepad.exe": NEUTRAL,
    "explorer.exe": NEUTRAL,
}


def default_category_for_basename(basename_lower: str) -> str:
    return _DEFAULT_BY_BASENAME.get(basename_lower, NEUTRAL)
