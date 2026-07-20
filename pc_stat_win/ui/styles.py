from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Template
from types import MappingProxyType
from typing import Literal, Mapping, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette, QStyleHints

ThemeMode = Literal["system", "light", "dark"]
ResolvedTheme = Literal["light", "dark"]

ACCENT = "#2563EB"

_LIGHT = {
    "window": "#EAF0F7",
    "window_tint": "rgba(238, 244, 250, 248)",
    "text": "#172033",
    "text_muted": "#5E6B7E",
    "text_disabled": "#667085",
    "surface": "#FFFFFF",
    "surface_glass": "rgba(255, 255, 255, 235)",
    "surface_glass_strong": "rgba(255, 255, 255, 249)",
    "surface_hover": "rgba(241, 245, 249, 245)",
    "surface_pressed": "rgba(226, 232, 240, 242)",
    "surface_disabled": "rgba(241, 245, 249, 215)",
    "border": "rgba(100, 116, 139, 58)",
    "border_strong": "rgba(71, 85, 105, 104)",
    "control_border": "#7A8699",
    "control_border_strong": "#526075",
    "selection": "rgba(37, 99, 235, 32)",
    "selection_text": "#172033",
    "scroll_track": "rgba(226, 232, 240, 150)",
    "scroll_handle": "#778396",
    "accent": ACCENT,
    "accent_hover": "#1D4ED8",
    "accent_pressed": "#1E40AF",
    "accent_text": "#FFFFFF",
    "danger": "#DC2626",
    "success": "#137333",
}

_DARK = {
    "window": "#11151C",
    "window_tint": "rgba(17, 21, 28, 246)",
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
    "control_border": "#718096",
    "control_border_strong": "#A8B1C0",
    "selection": "rgba(37, 99, 235, 88)",
    "selection_text": "#FFFFFF",
    "scroll_track": "rgba(17, 24, 39, 145)",
    "scroll_handle": "rgba(148, 163, 184, 120)",
    "accent": ACCENT,
    "accent_hover": "#3B82F6",
    "accent_pressed": "#1D4ED8",
    "accent_text": "#FFFFFF",
    "danger": "#F87171",
    "success": "#6EE7A0",
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


def semantic_qpalette(
    theme: str,
    style_hints: QStyleHints | None = None,
) -> QPalette:
    """Build a native Qt palette so standard controls/icons follow the theme."""
    colors = semantic_palette(theme, style_hints)
    palette = QPalette()
    role_colors = {
        QPalette.ColorRole.Window: colors["window"],
        QPalette.ColorRole.WindowText: colors["text"],
        QPalette.ColorRole.Base: colors["surface"],
        QPalette.ColorRole.AlternateBase: colors["surface"],
        QPalette.ColorRole.ToolTipBase: colors["surface"],
        QPalette.ColorRole.ToolTipText: colors["text"],
        QPalette.ColorRole.Text: colors["text"],
        QPalette.ColorRole.Button: colors["surface"],
        QPalette.ColorRole.ButtonText: colors["text"],
        QPalette.ColorRole.BrightText: colors["accent_text"],
        QPalette.ColorRole.Highlight: colors["accent"],
        QPalette.ColorRole.HighlightedText: colors["accent_text"],
        QPalette.ColorRole.Link: colors["accent"],
        QPalette.ColorRole.PlaceholderText: colors["text_muted"],
    }
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, color in role_colors.items():
            palette.setColor(group, role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.PlaceholderText,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            role,
            QColor(colors["text_disabled"]),
        )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Button,
        QColor(colors["surface"]),
    )
    if hasattr(QPalette.ColorRole, "Accent"):
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            palette.setColor(group, QPalette.ColorRole.Accent, QColor(colors["accent"]))
    return palette


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
