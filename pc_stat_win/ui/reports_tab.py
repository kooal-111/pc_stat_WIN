from __future__ import annotations

from datetime import datetime
from math import ceil
from typing import Callable

from PySide6.QtCore import QEasingCurve, QMargins, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pc_stat_win.categories import (
    ALL_CATEGORY_KEYS,
    CATEGORY_LABELS_RU,
    OTHER,
)
from pc_stat_win.db import AppStat, Database, PeriodStats
from pc_stat_win.formatting import format_duration_ms
from pc_stat_win.periods import Period, period_title
from pc_stat_win.ui.styles import semantic_palette

_WEEKDAYS_SHORT_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_MONTHS_SHORT_RU = (
    "янв.",
    "февр.",
    "мар.",
    "апр.",
    "май",
    "июн.",
    "июл.",
    "авг.",
    "сент.",
    "окт.",
    "нояб.",
    "дек.",
)

_REPORT_CATEGORY_COLORS = {
    "light": {
        "work": "#2563EB",
        "distraction": "#DC2626",
        "communication": "#0891B2",
        "games": "#7C3AED",
        "media": "#D97706",
        "devtools": "#059669",
        "system": "#64748B",
        "browser": "#0E7490",
        "office_docs": "#0D9488",
        "creative": "#BE185D",
        "remote_access": "#6D28D9",
        "files": "#65A30D",
        "ai_tools": "#4F46E5",
        "other": "#94A3B8",
    },
    "dark": {
        "work": "#60A5FA",
        "distraction": "#F87171",
        "communication": "#22D3EE",
        "games": "#A78BFA",
        "media": "#FBBF24",
        "devtools": "#34D399",
        "system": "#94A3B8",
        "browser": "#67E8F9",
        "office_docs": "#2DD4BF",
        "creative": "#F472B6",
        "remote_access": "#C4B5FD",
        "files": "#A3E635",
        "ai_tools": "#818CF8",
        "other": "#94A3B8",
    },
}
_REPORT_FADE_MS = 125


def _report_category_color(category: str, theme_key: str) -> str:
    theme = "light" if theme_key == "light" else "dark"
    return _REPORT_CATEGORY_COLORS[theme].get(
        category,
        _REPORT_CATEGORY_COLORS[theme]["other"],
    )


class _CategoryRow(QWidget):
    def __init__(self, category: str) -> None:
        super().__init__()
        self.category = category
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(10)

        self.dot = QLabel()
        self.dot.setFixedSize(8, 8)
        row.addWidget(self.dot)

        name = QLabel(CATEGORY_LABELS_RU.get(category, category))
        name.setMinimumWidth(130)
        row.addWidget(name)

        self.bar = QProgressBar()
        self.bar.setProperty("compact", True)
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(7)
        row.addWidget(self.bar, 1)

        self.value = QLabel()
        self.value.setObjectName("secondaryText")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setMinimumWidth(125)
        row.addWidget(self.value)

    def update_value(self, duration_ms: float, total_ms: float, theme_key: str) -> None:
        color = _report_category_color(self.category, theme_key)
        self.dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
        self.bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; }}"
        )
        pct = 100.0 * duration_ms / total_ms if total_ms > 0 else 0.0
        self.bar.setValue(max(0, min(1000, int(round(pct * 10)))))
        self.value.setText(f"{format_duration_ms(duration_ms)}  {pct:.1f}%")


class _UsageRow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 7, 0, 7)
        row.setSpacing(10)

        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        row.addWidget(self.dot)

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(3)
        self.name = QLabel()
        self.name.setObjectName("usageName")
        self.meta = QLabel()
        self.meta.setObjectName("secondaryText")
        self.bar = QProgressBar()
        self.bar.setProperty("compact", True)
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        content.addWidget(self.name)
        content.addWidget(self.meta)
        content.addWidget(self.bar)
        row.addLayout(content, 1)

        self.duration = QLabel()
        self.duration.setObjectName("usageDuration")
        self.duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.duration.setMinimumWidth(92)
        row.addWidget(self.duration)

    def update_app(
        self,
        app: AppStat,
        category: str,
        maximum_ms: float,
        theme_key: str,
    ) -> None:
        label = CATEGORY_LABELS_RU.get(category, category)
        color = _report_category_color(category, theme_key)
        self.dot.setStyleSheet(f"background-color: {color}; border-radius: 5px;")
        self.name.setText(app.exe_name or "Неизвестное приложение")
        self.name.setToolTip(app.exe_path)
        self.meta.setText(label)
        self.duration.setText(format_duration_ms(app.active_ms))
        self.bar.setStyleSheet(
            f"QProgressBar::chunk {{ background-color: {color}; }}"
        )
        pct = 1000.0 * app.active_ms / maximum_ms if maximum_ms > 0 else 0.0
        self.bar.setValue(max(0, min(1000, int(round(pct)))))


class _UsageList(QFrame):
    def __init__(self, title: str, empty_text: str) -> None:
        super().__init__()
        self.setObjectName("glassSurface")
        self._empty_text = empty_text
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(0)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        self._empty = QLabel(empty_text)
        self._empty.setObjectName("secondaryText")
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)
        self.rows = [_UsageRow() for _ in range(5)]
        for row in self.rows:
            row.hide()
            layout.addWidget(row)
        layout.addStretch(1)

    def update_apps(
        self,
        apps: list[AppStat],
        resolve_category: Callable[[str], str],
        theme_key: str,
    ) -> None:
        visible = apps[: len(self.rows)]
        self._empty.setVisible(not visible)
        maximum = max((app.active_ms for app in visible), default=0.0)
        for index, row in enumerate(self.rows):
            if index >= len(visible):
                row.hide()
                continue
            app = visible[index]
            category = app.category or resolve_category(app.exe_path)
            row.update_app(app, category, maximum, theme_key)
            row.show()


class ReportsTab(QWidget):
    """Screen Time-style reports page with lazy QtCharts loading."""

    navigate_requested = Signal(int)
    current_period_requested = Signal()

    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db
        self._stats: PeriodStats | None = None
        self._active = False
        self._chart_ready = False
        self._chart_failed = False
        self._theme_key = "dark"
        self._text_color = QColor("#f4f7fb")
        self._muted_color = QColor("#9ca8b8")
        self._grid_color = QColor(148, 163, 184, 45)
        self._fallback_bar_color = QColor("#22d3ee")
        self._uncovered_color = QColor("#94a3b8")
        self._summary_fade_animation: QPropertyAnimation | None = None
        self._summary_fade_effect: QGraphicsOpacityEffect | None = None
        self._period: Period = "week"
        self._period_offset = 0

        scroll = QScrollArea(self)
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setObjectName("pageContent")
        inner.setMinimumWidth(0)
        inner.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 4, 8, 16)
        layout.setSpacing(12)

        navigator = QFrame()
        navigator.setObjectName("reportNavigator")
        navigator_layout = QHBoxLayout(navigator)
        navigator_layout.setContentsMargins(10, 8, 10, 8)
        navigator_layout.setSpacing(8)
        self._previous_button = self._navigation_button(
            "‹",
            "Предыдущий период",
            -1,
        )
        navigator_layout.addWidget(self._previous_button)
        self._range_label = QLabel()
        self._range_label.setObjectName("periodRangeTitle")
        self._range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._range_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        navigator_layout.addWidget(self._range_label, 1)
        self._current_button = QPushButton("К текущему")
        self._current_button.setProperty("flatAction", True)
        self._current_button.clicked.connect(self.current_period_requested.emit)
        self._current_button.setAccessibleName("Вернуться к текущему периоду")
        navigator_layout.addWidget(self._current_button)
        self._next_button = self._navigation_button(
            "›",
            "Следующий период",
            1,
        )
        navigator_layout.addWidget(self._next_button)
        layout.addWidget(navigator)

        summary = QFrame()
        summary.setObjectName("screenTimeCard")
        summary_layout = QVBoxLayout(summary)
        summary_layout.setContentsMargins(18, 16, 18, 14)
        summary_layout.setSpacing(8)

        self._summary = summary
        summary_header = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._summary_header = summary_header
        summary_copy = QVBoxLayout()
        summary_copy.setSpacing(2)
        title = QLabel("Экранное время")
        title.setObjectName("sectionTitle")
        self._average_caption = QLabel("В среднем в день")
        self._average_caption.setObjectName("secondaryText")
        self._active_value = QLabel("—")
        self._active_value.setObjectName("reportHeroValue")
        summary_copy.addWidget(title)
        summary_copy.addWidget(self._average_caption)
        summary_copy.addWidget(self._active_value)
        summary_header.addLayout(summary_copy, 1)
        self._comparison_value = QLabel("Нет данных для сравнения")
        self._comparison_value.setObjectName("comparisonText")
        self._comparison_value.setWordWrap(True)
        self._comparison_value.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        summary_header.addWidget(self._comparison_value)
        summary_layout.addLayout(summary_header)

        self._chart_host = QWidget()
        self._chart_host.setMinimumWidth(0)
        self._chart_host.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._chart_layout = QVBoxLayout(self._chart_host)
        self._chart_layout.setContentsMargins(0, 0, 0, 0)
        self._chart_placeholder = QLabel("График появится при открытии отчёта")
        self._chart_placeholder.setObjectName("secondaryText")
        self._chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_placeholder.setMinimumHeight(245)
        self._chart_layout.addWidget(self._chart_placeholder)
        summary_layout.addWidget(self._chart_host)

        self._overview_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._category_summary: list[tuple[QWidget, QLabel, QLabel, QLabel]] = []
        for _index in range(3):
            block = QWidget()
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(0, 0, 0, 0)
            block_layout.setSpacing(1)
            name_row = QHBoxLayout()
            name_row.setContentsMargins(0, 0, 0, 0)
            name_row.setSpacing(6)
            dot = QLabel()
            dot.setFixedSize(8, 8)
            name = QLabel()
            name.setObjectName("reportCategoryName")
            value = QLabel()
            value.setObjectName("reportCategoryValue")
            name_row.addWidget(dot)
            name_row.addWidget(name, 1)
            block_layout.addLayout(name_row)
            block_layout.addWidget(value)
            self._overview_layout.addWidget(block, 1)
            self._category_summary.append((block, dot, name, value))
        summary_layout.addLayout(self._overview_layout)

        divider = QFrame()
        divider.setObjectName("reportDivider")
        divider.setFixedHeight(1)
        summary_layout.addWidget(divider)
        footer = QHBoxLayout()
        footer.addWidget(QLabel("Всего активного времени"))
        footer.addStretch(1)
        self._coverage_value = QLabel()
        self._coverage_value.setObjectName("secondaryText")
        footer.addWidget(self._coverage_value)
        self._total_value = QLabel("—")
        self._total_value.setObjectName("reportTotalValue")
        footer.addWidget(self._total_value)
        summary_layout.addLayout(footer)
        layout.addWidget(summary)

        categories = QFrame()
        categories.setObjectName("glassSurface")
        cat_layout = QVBoxLayout(categories)
        cat_layout.setContentsMargins(16, 14, 16, 14)
        cat_layout.setSpacing(4)
        cat_title = QLabel("Категории")
        cat_title.setObjectName("sectionTitle")
        cat_layout.addWidget(cat_title)
        caption = QLabel(
            "Доля от времени, для которого определено активное приложение"
        )
        caption.setObjectName("secondaryText")
        caption.setWordWrap(True)
        cat_layout.addWidget(caption)
        self._category_rows: dict[str, _CategoryRow] = {}
        for category in ALL_CATEGORY_KEYS:
            item = _CategoryRow(category)
            item.hide()
            cat_layout.addWidget(item)
            self._category_rows[category] = item
        layout.addWidget(categories)

        self._lists_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._lists_layout.setSpacing(12)
        self._top_apps = _UsageList(
            "Чаще всего использовались",
            "За выбранный период пока нет данных",
        )
        self._lists_layout.addWidget(self._top_apps, 1)
        self._other_apps = _UsageList(
            "Нужно классифицировать",
            "Все заметные приложения уже распределены по категориям",
        )
        self._lists_layout.addWidget(self._other_apps, 1)
        layout.addLayout(self._lists_layout)
        layout.addStretch(1)

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self._apply_responsive_layout()
        self.set_period_context("week", 0)

    def _navigation_button(
        self,
        symbol: str,
        tooltip: str,
        direction: int,
    ) -> QToolButton:
        button = QToolButton()
        button.setProperty("reportNavigation", True)
        button.setText(symbol)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.clicked.connect(lambda _checked=False: self.navigate_requested.emit(direction))
        return button

    def _apply_responsive_layout(self) -> None:
        compact = self.width() < 860
        self._lists_layout.setDirection(
            QBoxLayout.Direction.TopToBottom
            if compact
            else QBoxLayout.Direction.LeftToRight
        )
        compact_header = self.width() < 760
        self._summary_header.setDirection(
            QBoxLayout.Direction.TopToBottom
            if compact_header
            else QBoxLayout.Direction.LeftToRight
        )
        comparison_alignment = (
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            if compact_header
            else Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom
        )
        self._comparison_value.setAlignment(comparison_alignment)
        self._current_button.setText("Сейчас" if compact else "К текущему")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._apply_responsive_layout()

    def set_active(self, active: bool) -> None:
        self._active = active

    def set_period_context(self, period: Period, offset: int) -> None:
        self._period = period
        self._period_offset = min(0, int(offset))
        navigable = period != "all"
        self._previous_button.setEnabled(navigable)
        self._next_button.setEnabled(navigable and self._period_offset < 0)
        self._current_button.setVisible(navigable and self._period_offset < 0)
        if self._stats is not None:
            self._range_label.setText(
                period_title(period, self._stats.q_from, self._stats.q_to)
            )

    def apply_chart_theme(self, theme_key: str) -> None:
        self._theme_key = theme_key
        palette = semantic_palette(theme_key)
        self._text_color = QColor(palette["text"])
        self._muted_color = QColor(palette["text_muted"])
        self._grid_color = QColor(palette["tone_slate"])
        self._grid_color.setAlpha(48 if theme_key == "light" else 54)
        self._fallback_bar_color = QColor(palette["accent"])
        self._uncovered_color = QColor(palette["tone_slate"])
        self._uncovered_color.setAlpha(150 if theme_key == "light" else 125)
        if self._chart_ready:
            self._apply_chart_palette()

    def refresh(
        self,
        stats: PeriodStats,
        period: Period | None = None,
        offset: int | None = None,
    ) -> None:
        self._stats = stats
        if period is not None:
            self.set_period_context(period, self._period_offset if offset is None else offset)
        elif offset is not None:
            self.set_period_context(self._period, offset)
        self._range_label.setText(period_title(self._period, stats.q_from, stats.q_to))

        day_count = self._calendar_day_count(stats.q_from, stats.q_to)
        if self._period in ("week", "month", "year"):
            self._average_caption.setText("В среднем в день")
            self._active_value.setText(format_duration_ms(stats.pc_ms / day_count))
        else:
            self._average_caption.setText("Активное время")
            self._active_value.setText(format_duration_ms(stats.pc_ms))
        self._total_value.setText(format_duration_ms(stats.pc_ms))
        self._coverage_value.setText(f"Покрытие {stats.coverage_pct:.1f}%  ·")
        self._comparison_value.setText(self._comparison_text(stats))

        ranked_categories = sorted(
            (
                (category, duration)
                for category, duration in stats.by_category.items()
                if duration > 0.5
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        for index, (block, dot, name, value) in enumerate(self._category_summary):
            if index >= len(ranked_categories):
                block.hide()
                continue
            category, duration = ranked_categories[index]
            name.setText(CATEGORY_LABELS_RU.get(category, category))
            color = _report_category_color(category, self._theme_key)
            dot.setStyleSheet(f"background-color: {color}; border-radius: 4px;")
            value.setText(format_duration_ms(duration))
            block.show()

        for key, row in self._category_rows.items():
            duration = stats.by_category.get(key, 0.0)
            row.setVisible(duration > 0.5)
            if duration > 0.5:
                row.update_value(duration, stats.app_ms, self._theme_key)

        self._top_apps.update_apps(stats.apps[:5], self._db.resolve_category, self._theme_key)
        unclassified = [
            app
            for app in stats.apps
            if (app.category or self._db.resolve_category(app.exe_path)) == OTHER
        ]
        self._other_apps.update_apps(
            unclassified[:5],
            self._db.resolve_category,
            self._theme_key,
        )
        if self._active:
            self._refresh_chart()
            self._fade_summary()

    def _fade_summary(self) -> None:
        if not self.isVisible():
            return
        self._stop_summary_fade()
        effect = QGraphicsOpacityEffect(self._summary)
        effect.setOpacity(0.90)
        self._summary.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self._summary)
        animation.setDuration(_REPORT_FADE_MS)
        animation.setStartValue(0.90)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def cleanup() -> None:
            if self._summary.graphicsEffect() is effect:
                self._summary.setGraphicsEffect(None)
            if self._summary_fade_animation is animation:
                self._summary_fade_animation = None
            if self._summary_fade_effect is effect:
                self._summary_fade_effect = None

        animation.finished.connect(cleanup)
        self._summary_fade_animation = animation
        self._summary_fade_effect = effect
        animation.start()

    def _stop_summary_fade(self) -> None:
        if self._summary_fade_animation is not None:
            self._summary_fade_animation.stop()
        if self._summary.graphicsEffect() is self._summary_fade_effect:
            self._summary.setGraphicsEffect(None)
        self._summary_fade_animation = None
        self._summary_fade_effect = None

    @staticmethod
    def _calendar_day_count(q_from: float, q_to: float) -> int:
        if q_to <= q_from:
            return 1
        local_tz = datetime.now().astimezone().tzinfo
        start = datetime.fromtimestamp(q_from, tz=local_tz).date()
        end = datetime.fromtimestamp(
            max(q_from, q_to - 0.001), tz=local_tz
        ).date()
        return max(1, (end - start).days + 1)

    @staticmethod
    def _comparison_text(stats: PeriodStats) -> str:
        previous = stats.previous_pc_ms
        if previous is None or previous <= 0:
            return "Нет данных для сравнения"
        delta_pct = 100.0 * (stats.pc_ms - previous) / previous
        if abs(delta_pct) < 0.05:
            return "Без изменений к прошлому периоду"
        arrow = "↑" if delta_pct > 0 else "↓"
        return f"{arrow} {abs(delta_pct):.0f}% к прошлому периоду"

    def _ensure_chart(self) -> bool:
        if self._chart_ready:
            return True
        if self._chart_failed:
            return False
        try:
            from PySide6.QtCharts import QChart, QChartView
        except ImportError:
            self._chart_failed = True
            self._chart_placeholder.setText("QtCharts недоступен в этой сборке")
            return False

        self._chart = QChart()
        self._chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)
        self._chart.setBackgroundVisible(False)
        self._chart.setPlotAreaBackgroundVisible(False)
        self._chart.setMargins(QMargins(0, 0, 0, 0))
        self._chart.legend().hide()
        self._chart_view = QChartView(self._chart)
        self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._chart_view.setMinimumWidth(0)
        self._chart_view.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._chart_view.setMinimumHeight(255)
        self._chart_layout.removeWidget(self._chart_placeholder)
        self._chart_placeholder.hide()
        self._chart_placeholder.deleteLater()
        self._chart_layout.addWidget(self._chart_view)
        self._chart_ready = True
        self._apply_chart_palette()
        return True

    def _apply_chart_palette(self) -> None:
        if not self._chart_ready:
            return
        transparent = QColor(0, 0, 0, 0)
        self._chart.setBackgroundVisible(False)
        self._chart.setBackgroundBrush(QBrush(transparent))
        self._chart.setPlotAreaBackgroundVisible(False)
        self._chart.setPlotAreaBackgroundBrush(QBrush(transparent))
        self._chart.legend().hide()
        for axis in self._chart.axes():
            axis.setLabelsBrush(QBrush(self._muted_color))
            if hasattr(axis, "setTitleBrush"):
                axis.setTitleBrush(QBrush(self._muted_color))
            if hasattr(axis, "setGridLinePen"):
                axis.setGridLinePen(QPen(self._grid_color, 1))

    def _refresh_chart(self) -> None:
        stats = self._stats
        if stats is None or not self._ensure_chart():
            return
        from PySide6.QtCharts import (
            QBarCategoryAxis,
            QBarSet,
            QStackedBarSeries,
            QValueAxis,
        )

        for axis in self._chart.axes():
            axis.setVisible(False)
            self._chart.removeAxis(axis)
            axis.deleteLater()
        self._chart.removeAllSeries()
        series_data, category_data = self._compressed_chart_data(stats, 62)
        if not series_data:
            self._chart.setTitle("Нет данных за выбранный период")
            self._apply_chart_palette()
            return
        self._chart.setTitle("")

        totals_by_category = sorted(
            (
                (category, sum(values))
                for category, values in category_data.items()
                if sum(values) > 0.5
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        selected = [category for category, _total in totals_by_category[:4]]
        bars = QStackedBarSeries()
        bars.setBarWidth(0.68)
        stacked_totals = [0.0 for _ in series_data]

        for category in selected:
            values = category_data[category]
            bar_set = QBarSet(CATEGORY_LABELS_RU.get(category, category))
            bar_set.setBrush(QBrush(QColor(_report_category_color(category, self._theme_key))))
            for index, duration_ms in enumerate(values):
                hours = duration_ms / 3_600_000.0
                bar_set.append(hours)
                stacked_totals[index] += hours
            bars.append(bar_set)

        remaining_categories = [
            category for category, _total in totals_by_category if category not in selected
        ]
        if remaining_categories:
            other_set = QBarSet("Остальные категории")
            other_set.setBrush(QBrush(QColor(_report_category_color(OTHER, self._theme_key))))
            for index in range(len(series_data)):
                hours = sum(category_data[key][index] for key in remaining_categories)
                hours /= 3_600_000.0
                other_set.append(hours)
                stacked_totals[index] += hours
            bars.append(other_set)

        if not selected and not remaining_categories:
            fallback = QBarSet("Активность")
            fallback.setBrush(QBrush(self._fallback_bar_color))
            for index, (_label, duration_ms) in enumerate(series_data):
                hours = duration_ms / 3_600_000.0
                fallback.append(hours)
                stacked_totals[index] = hours
            bars.append(fallback)

        uncovered = []
        for index, (_label, duration_ms) in enumerate(series_data):
            pc_hours = duration_ms / 3_600_000.0
            uncovered.append(max(0.0, pc_hours - stacked_totals[index]))
        if any(value > 0.001 for value in uncovered):
            uncovered_set = QBarSet("Без приложения")
            uncovered_set.setBrush(QBrush(self._uncovered_color))
            for value in uncovered:
                uncovered_set.append(value)
            bars.append(uncovered_set)
            stacked_totals = [
                total + missing for total, missing in zip(stacked_totals, uncovered)
            ]

        self._chart.addSeries(bars)
        self._chart.legend().hide()

        raw_labels = [label for label, _duration in series_data]
        axis_x = QBarCategoryAxis()
        axis_x.append(self._axis_labels(stats.chart_mode, raw_labels, self._period))
        axis_x.setGridLineVisible(False)
        self._chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        bars.attachAxis(axis_x)

        axis_y = QValueAxis()
        maximum = max(stacked_totals, default=0.0)
        axis_y.setRange(0, max(0.5, maximum * 1.12))
        axis_y.setTickCount(4)
        axis_y.setLabelFormat("%.1f")
        axis_y.setMinorGridLineVisible(False)
        self._chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        bars.attachAxis(axis_y)
        self._apply_chart_palette()

    @staticmethod
    def _axis_labels(mode: str, labels: list[str], period: Period) -> list[str]:
        if not labels:
            return []
        result: list[str] = []
        if mode == "hour":
            step = max(1, ceil(len(labels) / 6))
            for index, label in enumerate(labels):
                hour = label.rsplit(" ", 1)[-1].split(":", 1)[0]
                result.append(hour if index % step == 0 else "")
            return result

        if mode == "month":
            step = max(1, ceil(len(labels) / 12))
            for index, label in enumerate(labels):
                try:
                    year_text, month_text = label.split("-", 1)
                    month = int(month_text)
                except (TypeError, ValueError):
                    result.append(label if index % step == 0 else "")
                    continue
                if period == "year" and len(labels) <= 12:
                    result.append(_MONTHS_SHORT_RU[month - 1])
                elif index % step == 0:
                    result.append(
                        str(year_text) if month == 1 else _MONTHS_SHORT_RU[month - 1]
                    )
                else:
                    result.append("")
            return result

        parsed: list[datetime | None] = []
        for label in labels:
            try:
                parsed.append(datetime.fromisoformat(label))
            except (TypeError, ValueError):
                parsed.append(None)
        if period == "week" and len(labels) <= 8:
            return [
                _WEEKDAYS_SHORT_RU[value.weekday()] if value is not None else labels[index]
                for index, value in enumerate(parsed)
            ]

        step = max(1, ceil(len(labels) / 10))
        for index, value in enumerate(parsed):
            if index % step != 0 and index != len(labels) - 1:
                result.append("")
            elif value is None:
                result.append(labels[index])
            else:
                result.append(str(value.day))
        return result

    @staticmethod
    def _compressed_chart_data(
        stats: PeriodStats,
        limit: int,
    ) -> tuple[list[tuple[str, float]], dict[str, list[float]]]:
        source = stats.chart_series
        if len(source) <= limit:
            return list(source), {
                key: list(values[: len(source)])
                for key, values in stats.chart_by_category.items()
            }
        chunk_size = max(1, ceil(len(source) / limit))
        compressed: list[tuple[str, float]] = []
        categories = {key: [] for key in stats.chart_by_category}
        for offset in range(0, len(source), chunk_size):
            chunk = source[offset : offset + chunk_size]
            compressed.append((chunk[-1][0], sum(value for _label, value in chunk)))
            for key, values in stats.chart_by_category.items():
                categories[key].append(sum(values[offset : offset + len(chunk)]))
        return compressed, categories

    @staticmethod
    def _compress_series(
        series: list[tuple[str, float]], limit: int
    ) -> list[tuple[str, float]]:
        if len(series) <= limit:
            return list(series)
        chunk_size = max(1, ceil(len(series) / limit))
        compressed: list[tuple[str, float]] = []
        for offset in range(0, len(series), chunk_size):
            chunk = series[offset : offset + chunk_size]
            compressed.append((chunk[-1][0], sum(value for _label, value in chunk)))
        return compressed
