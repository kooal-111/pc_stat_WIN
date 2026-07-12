from __future__ import annotations

from math import ceil

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from pc_stat_win.categories import ALL_CATEGORY_KEYS, CATEGORY_COLORS, CATEGORY_LABELS_RU, OTHER
from pc_stat_win.db import Database, PeriodStats
from pc_stat_win.formatting import format_duration_ms


class _CategoryRow(QWidget):
    def __init__(self, category: str) -> None:
        super().__init__()
        self.category = category
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(10)

        dot = QLabel()
        dot.setObjectName("categoryDot")
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background-color: {CATEGORY_COLORS.get(category, '#94a3b8')}; border-radius: 4px;"
        )
        row.addWidget(dot)

        name = QLabel(CATEGORY_LABELS_RU.get(category, category))
        name.setMinimumWidth(130)
        row.addWidget(name)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        row.addWidget(self.bar, 1)

        self.value = QLabel()
        self.value.setObjectName("secondaryText")
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setMinimumWidth(145)
        row.addWidget(self.value)

    def update_value(self, duration_ms: float, total_ms: float) -> None:
        pct = 100.0 * duration_ms / total_ms if total_ms > 0 else 0.0
        self.bar.setValue(max(0, min(1000, int(round(pct * 10)))))
        self.value.setText(f"{format_duration_ms(duration_ms)}  {pct:.1f}%")


class ReportsTab(QWidget):
    """Lightweight reports page. QtCharts is imported only when this page is shown."""

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

        scroll = QScrollArea(self)
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget()
        inner.setObjectName("pageContent")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(4, 4, 8, 16)
        layout.setSpacing(12)

        overview = QFrame()
        overview.setObjectName("glassSurface")
        overview_layout = QHBoxLayout(overview)
        overview_layout.setContentsMargins(16, 14, 16, 14)
        self._active_value = self._metric(overview_layout, "Активное время")
        self._coverage_value = self._metric(overview_layout, "Покрытие приложениями")
        self._comparison_value = self._metric(overview_layout, "К прошлому периоду")
        layout.addWidget(overview)

        categories = QFrame()
        categories.setObjectName("glassSurface")
        cat_layout = QVBoxLayout(categories)
        cat_layout.setContentsMargins(16, 14, 16, 14)
        cat_layout.setSpacing(4)
        title = QLabel("Распределение по категориям")
        title.setObjectName("sectionTitle")
        cat_layout.addWidget(title)
        caption = QLabel("Доля считается от времени, покрытого приложениями в фокусе")
        caption.setObjectName("secondaryText")
        cat_layout.addWidget(caption)
        self._category_rows: dict[str, _CategoryRow] = {}
        for category in ALL_CATEGORY_KEYS:
            item = _CategoryRow(category)
            item.hide()
            cat_layout.addWidget(item)
            self._category_rows[category] = item
        layout.addWidget(categories)

        lists = QHBoxLayout()
        lists.setSpacing(12)
        top_surface = QFrame()
        top_surface.setObjectName("glassSurface")
        top_layout = QVBoxLayout(top_surface)
        top_layout.setContentsMargins(16, 14, 16, 14)
        top_title = QLabel("Топ приложений")
        top_title.setObjectName("sectionTitle")
        top_layout.addWidget(top_title)
        self._top_apps = QLabel()
        self._top_apps.setWordWrap(True)
        self._top_apps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top_layout.addWidget(self._top_apps)
        lists.addWidget(top_surface, 1)

        other_surface = QFrame()
        other_surface.setObjectName("glassSurface")
        other_layout = QVBoxLayout(other_surface)
        other_layout.setContentsMargins(16, 14, 16, 14)
        other_title = QLabel("Нужно классифицировать")
        other_title.setObjectName("sectionTitle")
        other_layout.addWidget(other_title)
        self._other_apps = QLabel()
        self._other_apps.setWordWrap(True)
        self._other_apps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        other_layout.addWidget(self._other_apps)
        lists.addWidget(other_surface, 1)
        layout.addLayout(lists)

        timeline = QFrame()
        timeline.setObjectName("glassSurface")
        timeline_layout = QVBoxLayout(timeline)
        timeline_layout.setContentsMargins(12, 12, 12, 12)
        timeline_title = QLabel("Активность за период")
        timeline_title.setObjectName("sectionTitle")
        timeline_layout.addWidget(timeline_title)
        self._chart_host = QWidget()
        self._chart_layout = QVBoxLayout(self._chart_host)
        self._chart_layout.setContentsMargins(0, 0, 0, 0)
        self._chart_placeholder = QLabel("График появится при открытии отчёта")
        self._chart_placeholder.setObjectName("secondaryText")
        self._chart_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._chart_placeholder.setMinimumHeight(260)
        self._chart_layout.addWidget(self._chart_placeholder)
        timeline_layout.addWidget(self._chart_host)
        layout.addWidget(timeline)
        layout.addStretch(1)

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    @staticmethod
    def _metric(layout: QHBoxLayout, label: str) -> QLabel:
        block = QWidget()
        block_layout = QVBoxLayout(block)
        block_layout.setContentsMargins(0, 0, 0, 0)
        name = QLabel(label)
        name.setObjectName("secondaryText")
        value = QLabel("—")
        value.setObjectName("metricValue")
        block_layout.addWidget(name)
        block_layout.addWidget(value)
        layout.addWidget(block, 1)
        return value

    def set_active(self, active: bool) -> None:
        self._active = active
        if active and self._stats is not None:
            self._refresh_chart()

    def apply_chart_theme(self, theme_key: str) -> None:
        self._theme_key = theme_key
        if theme_key == "light":
            self._text_color = QColor("#172033")
            self._muted_color = QColor("#657084")
        else:
            self._text_color = QColor("#f4f7fb")
            self._muted_color = QColor("#9ca8b8")
        if self._chart_ready:
            self._apply_chart_palette()

    def refresh(self, stats: PeriodStats) -> None:
        self._stats = stats
        self._active_value.setText(format_duration_ms(stats.pc_ms))
        self._coverage_value.setText(f"{stats.coverage_pct:.1f}%")
        previous = getattr(stats, "previous_pc_ms", None)
        if previous is None:
            self._comparison_value.setText("Нет сравнения")
        else:
            delta = stats.pc_ms - previous
            sign = "+" if delta >= 0 else "−"
            self._comparison_value.setText(f"{sign}{format_duration_ms(abs(delta))}")

        for key, row in self._category_rows.items():
            ms = stats.by_category.get(key, 0.0)
            row.setVisible(ms > 0.5)
            if ms > 0.5:
                row.update_value(ms, stats.app_ms)

        top_lines = []
        for index, app in enumerate(stats.apps[:5], 1):
            category = app.category or self._db.resolve_category(app.exe_path)
            top_lines.append(
                f"{index}. {app.exe_name or '?'}  ·  {format_duration_ms(app.active_ms)}  ·  "
                f"{CATEGORY_LABELS_RU.get(category, category)}"
            )
        self._top_apps.setText("\n".join(top_lines) if top_lines else "Пока нет данных")

        other = [
            app
            for app in stats.apps
            if (app.category or self._db.resolve_category(app.exe_path)) == OTHER
        ][:5]
        self._other_apps.setText(
            "\n".join(
                f"{index}. {app.exe_name or '?'}  ·  {format_duration_ms(app.active_ms)}"
                for index, app in enumerate(other, 1)
            )
            if other
            else "Все заметные приложения классифицированы"
        )
        if self._active:
            self._refresh_chart()

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
        self._chart_view = QChartView(self._chart)
        self._chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._chart_view.setMinimumHeight(280)
        self._chart_layout.removeWidget(self._chart_placeholder)
        self._chart_placeholder.deleteLater()
        self._chart_layout.addWidget(self._chart_view)
        self._chart_ready = True
        self._apply_chart_palette()
        return True

    def _apply_chart_palette(self) -> None:
        if not self._chart_ready:
            return
        background = QColor("#f8fafc") if self._theme_key == "light" else QColor("#171b22")
        plot = QColor("#eef2f7") if self._theme_key == "light" else QColor("#11151b")
        self._chart.setBackgroundBrush(QBrush(background))
        self._chart.setPlotAreaBackgroundVisible(True)
        self._chart.setPlotAreaBackgroundBrush(QBrush(plot))
        self._chart.setTitleBrush(QBrush(self._text_color))
        self._chart.legend().setLabelBrush(QBrush(self._text_color))
        for axis in self._chart.axes():
            axis.setLabelsBrush(QBrush(self._text_color))
            if hasattr(axis, "setTitleBrush"):
                axis.setTitleBrush(QBrush(self._text_color))
            if hasattr(axis, "setGridLinePen"):
                axis.setGridLinePen(QPen(self._muted_color, 1))

    def _refresh_chart(self) -> None:
        stats = self._stats
        if stats is None or not self._ensure_chart():
            return
        from PySide6.QtCharts import QBarCategoryAxis, QBarSeries, QBarSet, QValueAxis

        for axis in self._chart.axes():
            self._chart.removeAxis(axis)
        self._chart.removeAllSeries()
        series_data = self._compress_series(stats.chart_series, 62)
        if not series_data:
            self._chart.setTitle("Нет данных для графика активности")
            self._apply_chart_palette()
            return

        values = QBarSet("Активность, ч")
        values.setBrush(QBrush(QColor("#2563eb")))
        max_value = 0.0
        labels: list[str] = []
        label_step = max(1, ceil(len(series_data) / 16))
        for index, (label, duration_ms) in enumerate(series_data):
            hours = duration_ms / 3_600_000.0
            values << hours
            labels.append(label if index % label_step == 0 else "")
            max_value = max(max_value, hours)

        bars = QBarSeries()
        bars.append(values)
        self._chart.addSeries(bars)
        self._chart.setTitle(
            "Активность по часам" if stats.chart_mode == "hour" else "Активность по дням"
        )

        axis_x = QBarCategoryAxis()
        axis_x.append(labels)
        self._chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        bars.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setTitleText("Часы")
        axis_y.setRange(0, max(0.5, max_value * 1.15))
        self._chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        bars.attachAxis(axis_y)
        self._apply_chart_palette()

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
