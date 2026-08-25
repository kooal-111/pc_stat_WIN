from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRect,
    QRegularExpression,
    QSize,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from pc_stat_win.categories import CATEGORY_COLORS, CATEGORY_LABELS_RU, OTHER
from pc_stat_win.exe_metadata import friendly_app_name
from pc_stat_win.formatting import format_duration_ms
from pc_stat_win.ui.icons import app_icon_for_exe

FILTER_DELAY_MS = 120
SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1
CATEGORY_ROLE = int(Qt.ItemDataRole.UserRole) + 2
PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 3
SEARCH_ROLE = int(Qt.ItemDataRole.UserRole) + 4
UPDATE_ROLES = [
    int(Qt.ItemDataRole.DisplayRole),
    int(Qt.ItemDataRole.DecorationRole),
    int(Qt.ItemDataRole.ToolTipRole),
    int(SORT_ROLE),
    int(CATEGORY_ROLE),
    int(PATH_ROLE),
    int(SEARCH_ROLE),
]


class AppTableColumn(IntEnum):
    APPLICATION = 0
    CATEGORY = 1
    ACTIVE = 2
    SHARE = 3
    PATH = 4


_HEADERS = ("Приложение", "Категория", "Активно", "Доля", "Путь")


def _field(row: object, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


class AppTableModel(QAbstractTableModel):
    """Read-only application usage model with stable display and sort roles."""

    def __init__(
        self,
        rows: Sequence[object] | QObject = (),
        *,
        total_ms: float = 0.0,
        parent: QObject | None = None,
    ) -> None:
        if isinstance(rows, QObject):
            if parent is not None:
                raise TypeError("parent was provided twice")
            parent = rows
            rows = ()
        super().__init__(parent)
        self._rows = list(rows)
        self._display_cache = [self._cache_row(row) for row in self._rows]
        self._total_ms = max(0.0, float(total_ms))

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(_HEADERS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal and 0 <= section < len(_HEADERS):
            return _HEADERS[section]
        if orientation == Qt.Orientation.Vertical:
            return section + 1
        return None

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None

        row = self._rows[index.row()]
        column = AppTableColumn(index.column())
        display_name, path, category, search_text = self._display_cache[index.row()]
        active_ms = float(_field(row, "active_ms", 0.0) or 0.0)
        share = self._share_for(row, active_ms)

        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_value(column, display_name, category, active_ms, share, path)
        if role == Qt.ItemDataRole.DecorationRole and column == AppTableColumn.APPLICATION:
            return app_icon_for_exe(path)
        if role == Qt.ItemDataRole.ToolTipRole:
            if column == AppTableColumn.APPLICATION:
                return f"{display_name}\n{path}" if path else display_name
            if column == AppTableColumn.CATEGORY:
                return category
            if column == AppTableColumn.PATH:
                return path
        if role == Qt.ItemDataRole.TextAlignmentRole and column in (
            AppTableColumn.ACTIVE,
            AppTableColumn.SHARE,
        ):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role == SORT_ROLE:
            if column == AppTableColumn.ACTIVE:
                return active_ms
            if column == AppTableColumn.SHARE:
                return share
            return self._display_value(column, display_name, category, active_ms, share, path)
        if role == CATEGORY_ROLE:
            return category
        if role == PATH_ROLE:
            return path
        if role == SEARCH_ROLE:
            return search_text
        return None

    def set_rows(self, rows: Sequence[object], *, total_ms: float | None = None) -> None:
        new_rows = list(rows)
        new_display_cache = [self._cache_row(row) for row in new_rows]
        new_total_ms = self._total_ms if total_ms is None else max(0.0, float(total_ms))
        if self._can_update_in_place(new_rows):
            self._rows = new_rows
            self._display_cache = new_display_cache
            self._total_ms = new_total_ms
            if self._rows:
                top = self.index(0, 0)
                bottom = self.index(len(self._rows) - 1, len(_HEADERS) - 1)
                self.dataChanged.emit(top, bottom, UPDATE_ROLES)
            return

        self.beginResetModel()
        self._rows = new_rows
        self._display_cache = new_display_cache
        self._total_ms = new_total_ms
        self.endResetModel()

    def set_total_ms(self, total_ms: float) -> None:
        value = max(0.0, float(total_ms))
        if value == self._total_ms:
            return
        self._total_ms = value
        if self._rows:
            top = self.index(0, AppTableColumn.SHARE)
            bottom = self.index(len(self._rows) - 1, AppTableColumn.SHARE)
            self.dataChanged.emit(
                top,
                bottom,
                [Qt.ItemDataRole.DisplayRole, SORT_ROLE],
            )

    def row_at(self, row: int) -> object | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def _can_update_in_place(self, new_rows: Sequence[object]) -> bool:
        if len(new_rows) != len(self._rows):
            return False
        return all(
            self._identity(old) == self._identity(new)
            for old, new in zip(self._rows, new_rows)
        )

    @staticmethod
    def _identity(row: object) -> tuple[str, str]:
        return (
            str(_field(row, "exe_path", "") or ""),
            str(_field(row, "exe_name", "") or ""),
        )

    @classmethod
    def _cache_row(cls, row: object) -> tuple[str, str, str, str]:
        path = str(_field(row, "exe_path", "") or "")
        category = str(_field(row, "category", "") or OTHER)
        display_name = cls._display_name(row, path)
        title = str(_field(row, "window_title", "") or "")
        label = CATEGORY_LABELS_RU.get(category, category)
        haystack = " ".join((display_name, path, title, category, label)).casefold()
        return display_name, path, category, f"{category}\x1f{haystack}"

    def _share_for(self, row: object, active_ms: float) -> float:
        explicit = _field(row, "share_pct")
        if explicit is not None:
            return float(explicit)
        return 100.0 * active_ms / self._total_ms if self._total_ms > 0 else 0.0

    @staticmethod
    def _display_name(row: object, path: str) -> str:
        explicit = str(_field(row, "display_name", "") or "").strip()
        if explicit:
            return explicit
        if path:
            return friendly_app_name(path)
        exe_name = str(_field(row, "exe_name", "") or "").strip()
        if exe_name:
            return exe_name
        return Path(path).stem or path

    @staticmethod
    def _display_value(
        column: AppTableColumn,
        display_name: str,
        category: str,
        active_ms: float,
        share: float,
        path: str,
    ) -> str:
        if column == AppTableColumn.APPLICATION:
            return display_name
        if column == AppTableColumn.CATEGORY:
            return CATEGORY_LABELS_RU.get(category, category)
        if column == AppTableColumn.ACTIVE:
            return format_duration_ms(active_ms)
        if column == AppTableColumn.SHARE:
            return f"{share:.1f}%"
        return path


class AppFilterProxyModel(QSortFilterProxyModel):
    """Immediate proxy; callers own the 120 ms input debounce."""

    def __init__(self, parent: object | None = None) -> None:
        super().__init__(parent)
        self._filter_text = ""
        self._category = ""
        self.setDynamicSortFilter(True)
        self.setFilterKeyColumn(int(AppTableColumn.APPLICATION))
        self.setFilterRole(SEARCH_ROLE)
        self._update_filter_expression()

    @property
    def filter_text(self) -> str:
        return self._filter_text

    @property
    def category(self) -> str:
        return self._category

    def set_filter_text(self, text: str) -> None:
        value = " ".join(text.casefold().split())
        if value == self._filter_text:
            return
        self._filter_text = value
        self._update_filter_expression()

    def set_category(self, category: str | None) -> None:
        value = str(category or "")
        if value == self._category:
            return
        self._category = value
        self._update_filter_expression()

    def _update_filter_expression(self) -> None:
        category = QRegularExpression.escape(self._category)
        prefix = f"^{category}\\x1f" if category else r"^[^\x1f]*\x1f"
        terms = "".join(
            f"(?=.*{QRegularExpression.escape(term)})"
            for term in self._filter_text.split()
        )
        expression = QRegularExpression(
            prefix + terms + ".*$",
            QRegularExpression.PatternOption.CaseInsensitiveOption,
        )
        self.setFilterRegularExpression(expression)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        left_value = left.data(SORT_ROLE)
        right_value = right.data(SORT_ROLE)
        if isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
            return float(left_value) < float(right_value)
        if left_value is None:
            return right_value is not None
        if right_value is None:
            return False
        return str(left_value).casefold() < str(right_value).casefold()


class CategoryDotDelegate(QStyledItemDelegate):
    """Paint a compact category color dot followed by the category label."""

    _DOT_SIZE = 8
    _GAP = 8

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        text = styled.text
        styled.text = ""
        style = styled.widget.style() if styled.widget is not None else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)

        category = str(index.data(CATEGORY_ROLE) or OTHER)
        color = QColor(CATEGORY_COLORS.get(category, CATEGORY_COLORS[OTHER]))
        content = option.rect.adjusted(10, 0, -8, 0)
        dot_y = content.center().y() - self._DOT_SIZE // 2
        dot_rect = QRect(content.left(), dot_y, self._DOT_SIZE, self._DOT_SIZE)
        text_left = dot_rect.right() + 1 + self._GAP
        text_rect = QRect(text_left, content.top(), max(0, content.right() - text_left), content.height())

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(dot_rect)
        role = (
            QPalette.ColorRole.HighlightedText
            if option.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        )
        painter.setPen(option.palette.color(role))
        elided = QFontMetrics(option.font).elidedText(
            text,
            Qt.TextElideMode.ElideRight,
            text_rect.width(),
        )
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            elided,
        )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        size = super().sizeHint(option, index)
        return QSize(size.width(), max(36, size.height()))
