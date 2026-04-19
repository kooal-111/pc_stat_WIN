from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QVBoxLayout, QWidget

from pc_stat_win.categories import ALL_CATEGORY_KEYS, CATEGORY_LABELS_RU
from pc_stat_win.db import Database
from pc_stat_win.formatting import format_duration_ms

try:
    from PySide6.QtCharts import (
        QBarCategoryAxis,
        QBarSeries,
        QBarSet,
        QChart,
        QChartView,
        QPieSeries,
        QValueAxis,
    )

    _HAS_CHARTS = True
except ImportError:
    _HAS_CHARTS = False


class ReportsTab(QWidget):
    def __init__(self, db: Database) -> None:
        super().__init__()
        self._db = db
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self._summary = QLabel()
        self._summary.setObjectName("reportsSummary")
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)

        if _HAS_CHARTS:
            self._chart_pie = QChart()
            self._chart_pie.setTitle("Время по категориям")
            self._view_pie = QChartView(self._chart_pie)
            self._view_pie.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._view_pie.setMinimumHeight(280)
            layout.addWidget(self._view_pie)

            self._chart_bar = QChart()
            self._chart_bar.setTitle("Активность за период")
            self._view_bar = QChartView(self._chart_bar)
            self._view_bar.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._view_bar.setMinimumHeight(320)
            layout.addWidget(self._view_bar)
        else:
            layout.addWidget(
                QLabel("QtCharts недоступен — установите полный PySide6 с модулем QtCharts.")
            )

        scroll.setWidget(inner)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def apply_chart_theme(self, theme_key: str) -> None:
        """Согласовать фон графиков с QSS (светлая/тёмная тема)."""
        if not _HAS_CHARTS:
            return
        if theme_key == "light":
            bg = QColor("#f0f1f4")
            plot = QColor("#eceef2")
        else:
            bg = QColor("#1e1e2e")
            plot = QColor("#262636")
        br_bg = QBrush(bg)
        br_plot = QBrush(plot)
        for ch in (self._chart_pie, self._chart_bar):
            ch.setBackgroundVisible(True)
            ch.setBackgroundBrush(br_bg)
            ch.setPlotAreaBackgroundVisible(True)
            ch.setPlotAreaBackgroundBrush(br_plot)

    def refresh(self, q_from: float, q_to: float) -> None:
        pc_ms = self._db.total_pc_ms(q_from, q_to)
        by_cat = self._db.totals_by_category(q_from, q_to)
        apps = self._db.totals_by_app(q_from, q_to)

        lines = [
            f"Активное время ПК за период: {format_duration_ms(pc_ms)}.",
            "",
            "По категориям (по приложениям в фокусе):",
        ]
        for key in ALL_CATEGORY_KEYS:
            ms = by_cat.get(key, 0.0)
            if ms < 0.5:
                continue
            label = CATEGORY_LABELS_RU.get(key, key)
            pct = 100.0 * ms / pc_ms if pc_ms > 0 else 0.0
            lines.append(f"  • {label}: {format_duration_ms(ms)} ({pct:.1f}%)")
        lines.append("")
        lines.append("Топ-5 приложений:")
        for i, a in enumerate(apps[:5], start=1):
            c = self._db.resolve_category(a.exe_path)
            cn = CATEGORY_LABELS_RU.get(c, c)
            lines.append(f"  {i}. {a.exe_name or '?'} — {format_duration_ms(a.active_ms)} ({cn})")
        self._summary.setText("\n".join(lines))

        if not _HAS_CHARTS:
            return

        self._chart_pie.removeAllSeries()
        pie = QPieSeries()
        for key in ALL_CATEGORY_KEYS:
            ms = by_cat.get(key, 0.0)
            if ms > 0.5:
                pie.append(CATEGORY_LABELS_RU.get(key, key), ms)
        if pie.count() > 0:
            self._chart_pie.addSeries(pie)
            self._chart_pie.legend().setAlignment(Qt.AlignmentFlag.AlignRight)

        for ax in self._chart_bar.axes():
            self._chart_bar.removeAxis(ax)
        self._chart_bar.removeAllSeries()
        mode, series = self._db.chart_pc_active_series(q_from, q_to)
        if not series:
            self._chart_bar.setTitle("Нет данных для графика активности")
            return
        bar_set = QBarSet("Активность, ч")
        categories: list[str] = []
        max_v = 0.0
        for label, ms in series:
            h = ms / 3600000.0
            bar_set << h
            categories.append(label)
            max_v = max(max_v, h)
        bs = QBarSeries()
        bs.append(bar_set)
        self._chart_bar.addSeries(bs)
        self._chart_bar.setTitle(
            "Активность по часам" if mode == "hour" else "Активность по дням"
        )
        axis_x = QBarCategoryAxis()
        for c in categories:
            axis_x.append(c)
        self._chart_bar.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        bs.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setTitleText("Часы" if mode == "hour" else "Часы за день")
        axis_y.setRange(0, max(0.5, max_v * 1.15))
        self._chart_bar.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        bs.attachAxis(axis_y)
