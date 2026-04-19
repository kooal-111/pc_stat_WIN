from __future__ import annotations

from pathlib import Path


def load_stylesheet(theme: str) -> str:
    """theme: 'dark' | 'light'"""
    base = Path(__file__).resolve().parent
    name = "theme_dark.qss" if theme == "dark" else "theme_light.qss"
    return (base / name).read_text(encoding="utf-8")
