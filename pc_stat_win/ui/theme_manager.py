from __future__ import annotations

from weakref import WeakSet

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QWidget

from pc_stat_win.ui.styles import (
    ResolvedTheme,
    ThemeMode,
    normalize_theme,
    render_stylesheet,
    resolve_theme,
)
from pc_stat_win.ui.window_material import apply_window_material


class ThemeManager(QObject):
    """Own application theming and react to the platform color scheme."""

    theme_changed = Signal(str)

    def __init__(
        self,
        app: QApplication,
        mode: str = "system",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._app = app
        self._mode: ThemeMode = normalize_theme(mode)
        self._resolved: ResolvedTheme | None = None
        self._windows: WeakSet[QWidget] = WeakSet()
        self._style_hints = app.styleHints()
        self._style_hints.colorSchemeChanged.connect(self._on_system_scheme_changed)
        self.apply()

    @property
    def mode(self) -> ThemeMode:
        return self._mode

    @property
    def resolved_theme(self) -> ResolvedTheme:
        return self._resolved or resolve_theme(self._mode, self._style_hints)

    def set_mode(self, mode: str) -> None:
        normalized = normalize_theme(mode)
        if normalized == self._mode:
            return
        self._mode = normalized
        self.apply()

    def register_window(self, window: QWidget) -> None:
        self._windows.add(window)
        apply_window_material(window, dark=self.resolved_theme == "dark")

    def unregister_window(self, window: QWidget) -> None:
        self._windows.discard(window)

    def apply(self) -> None:
        resolved = resolve_theme(self._mode, self._style_hints)
        self._app.setProperty("themeMode", self._mode)
        self._app.setProperty("resolvedTheme", resolved)
        self._app.setStyleSheet(render_stylesheet(resolved))

        for window in tuple(self._windows):
            apply_window_material(window, dark=resolved == "dark")

        changed = resolved != self._resolved
        self._resolved = resolved
        if changed:
            self.theme_changed.emit(resolved)

    def _on_system_scheme_changed(self, _scheme: object) -> None:
        if self._mode == "system":
            self.apply()
