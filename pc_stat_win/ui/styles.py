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

ACCENT = "#0F766E"

_LIGHT = {
    "window": "#F4F7FA",
    "window_tint": "rgba(246, 248, 251, 248)",
    "text": "#171A21",
    "text_muted": "#5F6875",
    "text_disabled": "#667085",
    "surface": "#FFFFFF",
    "surface_glass": "rgba(255, 255, 255, 238)",
    "surface_glass_strong": "rgba(255, 255, 255, 249)",
    "surface_inner": "rgba(248, 250, 252, 245)",
    "surface_hover": "rgba(235, 240, 245, 246)",
    "surface_pressed": "rgba(217, 225, 233, 242)",
    "surface_disabled": "rgba(239, 243, 247, 218)",
    "border": "rgba(100, 116, 139, 58)",
    "border_strong": "rgba(71, 85, 105, 104)",
    "control_border": "#8792A1",
    "control_border_strong": "#5F6B7A",
    "selection": "rgba(15, 118, 110, 34)",
    "selection_text": "#171A21",
    "scroll_track": "rgba(222, 228, 235, 155)",
    "scroll_handle": "#768391",
    "accent": ACCENT,
    "accent_soft": "rgba(15, 118, 110, 30)",
    "accent_hover": "#0D9488",
    "accent_pressed": "#115E59",
    "accent_text": "#FFFFFF",
    "danger": "#DC2626",
    "danger_bg": "rgba(220, 38, 38, 24)",
    "success": "#137333",
    "success_bg": "rgba(19, 115, 51, 24)",
}

_DARK = {
    "window": "#121417",
    "window_tint": "rgba(18, 20, 23, 246)",
    "text": "#F4F7F8",
    "text_muted": "#A9B2B8",
    "text_disabled": "#697586",
    "surface": "#1C2024",
    "surface_glass": "rgba(28, 32, 36, 222)",
    "surface_glass_strong": "rgba(34, 39, 44, 240)",
    "surface_inner": "rgba(24, 28, 32, 238)",
    "surface_hover": "rgba(49, 57, 63, 226)",
    "surface_pressed": "rgba(64, 73, 80, 236)",
    "surface_disabled": "rgba(32, 37, 42, 192)",
    "border": "rgba(154, 166, 176, 72)",
    "border_strong": "rgba(154, 166, 176, 118)",
    "control_border": "#78848D",
    "control_border_strong": "#B5BEC5",
    "selection": "rgba(45, 212, 191, 74)",
    "selection_text": "#FFFFFF",
    "scroll_track": "rgba(16, 18, 20, 150)",
    "scroll_handle": "rgba(160, 172, 181, 125)",
    "accent": ACCENT,
    "accent_soft": "rgba(45, 212, 191, 34)",
    "accent_hover": "#14B8A6",
    "accent_pressed": "#0F766E",
    "accent_text": "#FFFFFF",
    "danger": "#F87171",
    "danger_bg": "rgba(248, 113, 113, 28)",
    "success": "#6EE7A0",
    "success_bg": "rgba(110, 231, 160, 26)",
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
