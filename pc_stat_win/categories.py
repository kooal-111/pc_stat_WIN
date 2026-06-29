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
BROWSER = "browser"
OFFICE_DOCS = "office_docs"
CREATIVE = "creative"
REMOTE_ACCESS = "remote_access"
FILES = "files"
AI_TOOLS = "ai_tools"
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
    BROWSER,
    OFFICE_DOCS,
    CREATIVE,
    REMOTE_ACCESS,
    FILES,
    AI_TOOLS,
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
    BROWSER: "Браузер / веб",
    OFFICE_DOCS: "Документы / офис",
    CREATIVE: "Дизайн / креатив",
    REMOTE_ACCESS: "Удалённый доступ",
    FILES: "Файлы / архивы",
    AI_TOOLS: "AI / ассистенты",
    OTHER: "Прочее / нейтрально",
}

CATEGORY_COLORS: dict[str, str] = {
    WORK: "#3b82f6",
    DISTRACTION: "#ef4444",
    COMMUNICATION: "#06b6d4",
    GAMES: "#a855f7",
    MEDIA: "#f59e0b",
    DEVTOOLS: "#10b981",
    SYSTEM: "#64748b",
    BROWSER: "#2563eb",
    OFFICE_DOCS: "#14b8a6",
    CREATIVE: "#ec4899",
    REMOTE_ACCESS: "#8b5cf6",
    FILES: "#84cc16",
    AI_TOOLS: "#6366f1",
    OTHER: "#94a3b8",
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
    (r"microsoft office", OFFICE_DOCS),
    (r"program files\google\chrome", BROWSER),
    (r"program files (x86)\google\chrome", BROWSER),
    (r"yandex\yandexbrowser", BROWSER),
    (r"adobe", CREATIVE),
    (r"obs studio", CREATIVE),
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
    "chrome.exe": BROWSER,
    "msedge.exe": BROWSER,
    "firefox.exe": BROWSER,
    "brave.exe": BROWSER,
    "opera.exe": BROWSER,
    "opera_gx.exe": BROWSER,
    "vivaldi.exe": BROWSER,
    "browser.exe": BROWSER,
    "yandexbrowser.exe": BROWSER,
    "steam.exe": GAMES,
    "epicgameslauncher.exe": GAMES,
    "riotclientservices.exe": GAMES,
    "devenv.exe": DEVTOOLS,
    "code.exe": DEVTOOLS,
    "cursor.exe": DEVTOOLS,
    "pycharm64.exe": DEVTOOLS,
    "webstorm64.exe": DEVTOOLS,
    "idea64.exe": DEVTOOLS,
    "windowsterminal.exe": DEVTOOLS,
    "powershell.exe": DEVTOOLS,
    "cmd.exe": SYSTEM,
    "winword.exe": OFFICE_DOCS,
    "excel.exe": OFFICE_DOCS,
    "powerpnt.exe": OFFICE_DOCS,
    "onenote.exe": OFFICE_DOCS,
    "acrord32.exe": OFFICE_DOCS,
    "acrobat.exe": OFFICE_DOCS,
    "sumatrapdf.exe": OFFICE_DOCS,
    "notepad.exe": OFFICE_DOCS,
    "notepad++.exe": OFFICE_DOCS,
    "figma.exe": CREATIVE,
    "photoshop.exe": CREATIVE,
    "illustrator.exe": CREATIVE,
    "blender.exe": CREATIVE,
    "gimp.exe": CREATIVE,
    "inkscape.exe": CREATIVE,
    "resolve.exe": CREATIVE,
    "obs64.exe": CREATIVE,
    "mstsc.exe": REMOTE_ACCESS,
    "anydesk.exe": REMOTE_ACCESS,
    "teamviewer.exe": REMOTE_ACCESS,
    "rustdesk.exe": REMOTE_ACCESS,
    "parsecd.exe": REMOTE_ACCESS,
    "explorer.exe": FILES,
    "totalcmd.exe": FILES,
    "totalcmd64.exe": FILES,
    "7zfm.exe": FILES,
    "winrar.exe": FILES,
    "everything.exe": FILES,
    "chatgpt.exe": AI_TOOLS,
    "claude.exe": AI_TOOLS,
    "copilot.exe": AI_TOOLS,
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
