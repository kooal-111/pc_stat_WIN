from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template
from types import MappingProxyType
from typing import Literal, Mapping, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPalette, QStyleHints

ThemeMode = Literal["system", "light", "dark"]
ResolvedTheme = Literal["light", "dark"]

ACCENT = "#2563EB"

_LIGHT = {
    "window": "#EEF2F7",
    "text": "#172033",
    "text_muted": "#5E6B7E",
    "text_disabled": "#98A2B3",
    "surface": "#FFFFFF",
    "surface_glass": "rgba(255, 255, 255, 214)",
    "surface_glass_strong": "rgba(255, 255, 255, 235)",
    "surface_hover": "rgba(226, 232, 240, 224)",
    "surface_pressed": "rgba(203, 213, 225, 235)",
    "surface_disabled": "rgba(226, 232, 240, 190)",
    "border": "rgba(100, 116, 139, 92)",
    "border_strong": "rgba(71, 85, 105, 135)",
    "selection": "rgba(37, 99, 235, 38)",
    "selection_text": "#172033",
    "scroll_track": "rgba(226, 232, 240, 150)",
    "scroll_handle": "rgba(100, 116, 139, 145)",
    "accent": ACCENT,
    "accent_hover": "#1D4ED8",
    "accent_pressed": "#1E40AF",
    "accent_text": "#FFFFFF",
    "danger": "#DC2626",
}

_DARK = {
    "window": "#11151C",
    "text": "#F3F6FA",
    "text_muted": "#A8B1C0",
    "text_disabled": "#697586",
    "surface": "#1B212B",
    "surface_glass": "rgba(27, 33, 43, 218)",
    "surface_glass_strong": "rgba(31, 38, 49, 238)",
    "surface_hover": "rgba(55, 65, 81, 224)",
    "surface_pressed": "rgba(71, 85, 105, 235)",
    "surface_disabled": "rgba(30, 38, 49, 190)",
    "border": "rgba(148, 163, 184, 70)",
    "border_strong": "rgba(148, 163, 184, 115)",
    "selection": "rgba(37, 99, 235, 88)",
    "selection_text": "#FFFFFF",
    "scroll_track": "rgba(17, 24, 39, 145)",
    "scroll_handle": "rgba(148, 163, 184, 120)",
    "accent": ACCENT,
    "accent_hover": "#3B82F6",
    "accent_pressed": "#1D4ED8",
    "accent_text": "#FFFFFF",
    "danger": "#F87171",
}

SEMANTIC_PALETTES: Mapping[ResolvedTheme, Mapping[str, str]] = MappingProxyType(
    {
        "light": MappingProxyType(_LIGHT),
        "dark": MappingProxyType(_DARK),
    }
)


def normalize_theme(theme: str) -> ThemeMode:
    value = theme.strip().lower()
    if value not in ("system", "light", "dark"):
        raise ValueError(f"Unsupported theme mode: {theme!r}")
    return cast(ThemeMode, value)


def system_theme(style_hints: QStyleHints | None = None) -> ResolvedTheme:
    hints = style_hints
    if hints is None:
        app = QGuiApplication.instance()
        hints = app.styleHints() if app is not None else None

    if hints is not None and hasattr(hints, "colorScheme"):
        scheme = hints.colorScheme()
        if scheme == Qt.ColorScheme.Light:
            return "light"
        if scheme == Qt.ColorScheme.Dark:
            return "dark"

    app = QGuiApplication.instance()
    if app is not None:
        color = app.palette().color(QPalette.ColorRole.Window)
        return "dark" if color.lightness() < 128 else "light"
    return "dark"


def resolve_theme(
    theme: str,
    style_hints: QStyleHints | None = None,
) -> ResolvedTheme:
    mode = normalize_theme(theme)
    return system_theme(style_hints) if mode == "system" else mode


def semantic_palette(
    theme: str,
    style_hints: QStyleHints | None = None,
) -> Mapping[str, str]:
    return SEMANTIC_PALETTES[resolve_theme(theme, style_hints)]


@lru_cache(maxsize=1)
def _stylesheet_template() -> Template:
    path = Path(__file__).resolve().with_name("theme.qss")
    return Template(path.read_text(encoding="utf-8"))


def render_stylesheet(
    theme: str = "system",
    style_hints: QStyleHints | None = None,
) -> str:
    palette = semantic_palette(theme, style_hints)
    rendered = _stylesheet_template().substitute(palette)
    if "${" in rendered:
        raise ValueError("Unresolved semantic token in theme.qss")
    return rendered


def load_stylesheet(theme: str) -> str:
    """Render the shared QSS template for system, light, or dark mode."""
    return render_stylesheet(theme)
