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

ACCENT = "#0E7490"

_LIGHT = {
    "window": "#F6F8FB",
    "window_tint": "rgba(246, 248, 251, 248)",
    "text": "#111827",
    "text_muted": "#5B6472",
    "text_disabled": "#6B7280",
    "surface": "#FFFFFF",
    "surface_glass": "rgba(255, 255, 255, 242)",
    "surface_glass_strong": "rgba(255, 255, 255, 252)",
    "surface_inner": "rgba(248, 251, 253, 246)",
    "surface_hover": "rgba(232, 240, 247, 246)",
    "surface_pressed": "rgba(213, 226, 237, 242)",
    "surface_disabled": "rgba(238, 243, 248, 220)",
    "border": "rgba(92, 111, 128, 58)",
    "border_strong": "rgba(72, 87, 105, 108)",
    "control_border": "#8290A1",
    "control_border_strong": "#52677C",
    "selection": "rgba(14, 116, 144, 76)",
    "selection_soft": "rgba(14, 116, 144, 34)",
    "selection_strong": "rgba(14, 116, 144, 76)",
    "selection_text": "#0F172A",
    "scroll_track": "rgba(220, 228, 238, 160)",
    "scroll_handle": "#738195",
    "accent": ACCENT,
    "accent_soft": "rgba(14, 116, 144, 34)",
    "accent_hover": "#0891B2",
    "accent_pressed": "#155E75",
    "accent_text": "#FFFFFF",
    "danger": "#DC2626",
    "danger_bg": "rgba(220, 38, 38, 24)",
    "success": "#16803A",
    "success_bg": "rgba(22, 128, 58, 24)",
    "warning": "#B45309",
    "warning_bg": "rgba(180, 83, 9, 24)",
    "tone_blue": "#2563EB",
    "tone_teal": "#0E7490",
    "tone_violet": "#7C3AED",
    "tone_amber": "#D97706",
    "tone_rose": "#DB2777",
    "tone_slate": "#64748B",
}

_DARK = {
    "window": "#101418",
    "window_tint": "rgba(16, 20, 24, 246)",
    "text": "#F6F8FB",
    "text_muted": "#AAB4C0",
    "text_disabled": "#687586",
    "surface": "#1A2027",
    "surface_glass": "rgba(27, 33, 40, 226)",
    "surface_glass_strong": "rgba(32, 40, 51, 242)",
    "surface_inner": "rgba(20, 26, 32, 238)",
    "surface_hover": "rgba(43, 52, 63, 230)",
    "surface_pressed": "rgba(58, 68, 82, 238)",
    "surface_disabled": "rgba(29, 35, 43, 196)",
    "border": "rgba(148, 163, 184, 72)",
    "border_strong": "rgba(168, 182, 198, 126)",
    "control_border": "#718096",
    "control_border_strong": "#AAB7C4",
    "selection": "rgba(34, 211, 238, 76)",
    "selection_soft": "rgba(34, 211, 238, 34)",
    "selection_strong": "rgba(34, 211, 238, 76)",
    "selection_text": "#F8FCFF",
    "scroll_track": "rgba(8, 12, 16, 160)",
    "scroll_handle": "rgba(170, 184, 198, 132)",
    "accent": "#22D3EE",
    "accent_soft": "rgba(34, 211, 238, 34)",
    "accent_hover": "#67E8F9",
    "accent_pressed": "#06B6D4",
    "accent_text": "#06242B",
    "danger": "#F87171",
    "danger_bg": "rgba(248, 113, 113, 28)",
    "success": "#6EE7A0",
    "success_bg": "rgba(110, 231, 160, 26)",
    "warning": "#FBBF24",
    "warning_bg": "rgba(251, 191, 36, 26)",
    "tone_blue": "#60A5FA",
    "tone_teal": "#22D3EE",
    "tone_violet": "#A78BFA",
    "tone_amber": "#FBBF24",
    "tone_rose": "#F472B6",
    "tone_slate": "#94A3B8",
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
