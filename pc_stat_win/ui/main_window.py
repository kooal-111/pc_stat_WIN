from __future__ import annotations

import time
from functools import partial

import psutil
from PySide6.QtCore import QSize, Qt, QTimer, Slot
from PySide6.QtGui import QBrush, QCloseEvent, QColor, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from pc_stat_win import autostart
from pc_stat_win.categories import CATEGORY_COLORS, CATEGORY_LABELS_RU, OTHER
from pc_stat_win.collector import UsageCollector
from pc_stat_win.config import UI_REFRESH_INTERVAL_MS
from pc_stat_win.db import AppStat, Database, PeriodStats
from pc_stat_win.exe_metadata import friendly_app_name
from pc_stat_win.export import export_apps_csv
from pc_stat_win.formatting import format_duration_ms, format_duration_seconds
from pc_stat_win.periods import Period, period_range, previous_period_range
from pc_stat_win.ui.icons import app_icon_for_exe
from pc_stat_win.ui.reports_tab import ReportsTab
from pc_stat_win.ui.styles import load_stylesheet


class SortableItem(QTableWidgetItem):
    def __lt__(self, other: QTableWidgetItem) -> bool:
        left = self.data(Qt.ItemDataRole.UserRole)
        right = other.data(Qt.ItemDataRole.UserRole)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return float(left) < float(right)
        return super().__lt__(other)


class MainWindow(QMainWindow):
    def __init__(
        self,
        db: Database,
        collector: UsageCollector,
        *,
        window_icon: QIcon | None = None,
        tray_available: bool = True,
    ) -> None:
        super().__init__()
        self._db = db
        self._collector = collector
        self._tray_available = tray_available
        self._last_stats: PeriodStats | None = None
        self._refresh_dirty = True
        self.setWindowTitle("PC Stat — активность")
        if window_icon is not None and not window_icon.isNull():
            self.setWindowIcon(window_icon)
        self.setMinimumSize(920, 640)
        self._build()
        self._collector.tick_done.connect(self._mark_refresh_dirty)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(UI_REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._refresh_if_dirty)
        self._refresh_timer.start()
        self._optimize_timer = QTimer(self)
        self._optimize_timer.setInterval(10 * 60 * 1000)
        self._optimize_timer.timeout.connect(self._db.optimize)
        self._optimize_timer.start()
        self.refresh_stats(force_reports=True)

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self._tabs)

        # --- Stats tab ---
        stats_w = QWidget()
        stats_layout = QVBoxLayout(stats_w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Период:"))

        self._period_buttons: dict[Period, QPushButton] = {}
        self._period_group = QButtonGroup(self)
        self._period_group.setExclusive(True)
        period_buttons: list[tuple[str, Period, str]] = [
            ("Сегодня", "today", "periodToday"),
            ("Неделя", "week", "periodWeek"),
            ("Месяц", "month", "periodMonth"),
            ("Год", "year", "periodYear"),
            ("Всё время", "all", "periodAll"),
        ]
        for label, key, oid in period_buttons:
            b = QPushButton(label)
            b.setObjectName(oid)
            b.setProperty("segment", True)
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.clicked.connect(partial(self._set_period, key))
            self._period_buttons[key] = b
            self._period_group.addButton(b)
            top.addWidget(b)

        top.addStretch(1)
        self._btn_export = QPushButton("Экспорт CSV…")
        self._btn_export.setObjectName("btnExport")
        self._btn_export.clicked.connect(self._export_csv)
        top.addWidget(self._btn_export)

        stats_layout.addLayout(top)

        filters = QHBoxLayout()
        filters.addWidget(QLabel("Фильтр:"))
        self._filter_search = QLineEdit()
        self._filter_search.setPlaceholderText("поиск по приложению или пути")
        self._filter_search.textChanged.connect(lambda _text: self._apply_current_stats())
        filters.addWidget(self._filter_search, stretch=2)
        self._filter_cat = QComboBox()
        self._filter_cat.addItem("Все категории", "")
        for key, label in CATEGORY_LABELS_RU.items():
            self._filter_cat.addItem(label, key)
        self._filter_cat.currentIndexChanged.connect(lambda _idx: self._apply_current_stats())
        filters.addWidget(self._filter_cat)
        self._btn_rule_from_app = QPushButton("Создать правило")
        self._btn_rule_from_app.clicked.connect(self._create_rule_from_selected_app)
        filters.addWidget(self._btn_rule_from_app)
        stats_layout.addLayout(filters)

        card = QFrame()
        card.setObjectName("card")
        card_l = QVBoxLayout(card)
        kpi_row = QHBoxLayout()
        self._kpi_labels: dict[str, QLabel] = {}
        for key, title in (
            ("active", "Активно"),
            ("uptime", "Работа ПК"),
            ("share", "Доля активности"),
            ("coverage", "Покрытие прилож."),
            ("apps", "Приложений"),
            ("session", "Сессия"),
        ):
            kpi = QFrame()
            kpi.setObjectName("kpiCard")
            kpi_l = QVBoxLayout(kpi)
            name = QLabel(title)
            name.setObjectName("kpiLabel")
            value = QLabel("—")
            value.setObjectName("kpiValue")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            kpi_l.addWidget(name)
            kpi_l.addWidget(value)
            kpi_row.addWidget(kpi)
            self._kpi_labels[key] = value
        card_l.addLayout(kpi_row)
        self._period_stats = QLabel()
        self._period_stats.setObjectName("periodStatsLabel")
        self._period_stats.setWordWrap(True)
        card_l.addWidget(self._period_stats)
        stats_layout.addWidget(card)

        top5_box = QGroupBox("Топ-5 приложений по активному времени")
        top5_box.setObjectName("top5Group")
        top5_l = QVBoxLayout(top5_box)
        self._top5_bars: list[tuple[QLabel, QProgressBar]] = []
        for idx in range(5):
            row = QHBoxLayout()
            name_lbl = QLabel("—")
            name_lbl.setMinimumWidth(180)
            name_lbl.setObjectName(f"top5name{idx}")
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setFormat("—")
            bar.setObjectName(f"top5bar{idx}")
            bar.setMinimumHeight(22)
            row.addWidget(name_lbl)
            row.addWidget(bar, stretch=1)
            top5_l.addLayout(row)
            self._top5_bars.append((name_lbl, bar))
        stats_layout.addWidget(top5_box)

        self._table = QTableWidget(0, 5)
        self._table.setObjectName("appsTable")
        self._table.setAlternatingRowColors(True)
        self._table.setIconSize(QSize(28, 28))
        self._table.setShowGrid(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setHorizontalHeaderLabels(
            ["Приложение", "Категория", "Активно", "Доля", "Путь"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        stats_layout.addWidget(self._table)

        self._tabs.addTab(stats_w, "Статистика")

        # --- Reports ---
        self._reports = ReportsTab(self._db)
        self._tabs.addTab(self._reports, "Отчёты")

        # --- Categories ---
        cat_w = QWidget()
        cat_l = QVBoxLayout(cat_w)
        cat_l.addWidget(
            QLabel(
                "Правила сопоставляются сверху вниз (приоритет). "
                "«Точное имя exe» — только basename; «Фрагмент пути» — подстрока в полном пути."
            )
        )
        self._rules_table = QTableWidget(0, 5)
        self._rules_table.setHorizontalHeaderLabels(["ID", "Приоритет", "Шаблон", "Тип", "Категория"])
        self._rules_table.hideColumn(0)
        self._rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._rules_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._rules_table.itemSelectionChanged.connect(self._load_selected_rule)
        cat_l.addWidget(self._rules_table)

        form = QHBoxLayout()
        self._rule_match = QLineEdit()
        self._rule_match.setPlaceholderText("chrome.exe или Games")
        self._rule_kind = QComboBox()
        self._rule_kind.addItem("Точное имя exe", "exact_basename")
        self._rule_kind.addItem("Фрагмент пути", "path_contains")
        self._rule_cat = QComboBox()
        for key, lab in CATEGORY_LABELS_RU.items():
            self._rule_cat.addItem(lab, key)
        self._btn_rule_add = QPushButton("Добавить")
        self._btn_rule_add.clicked.connect(self._add_category_rule)
        self._btn_rule_save = QPushButton("Сохранить")
        self._btn_rule_save.clicked.connect(self._save_category_rule)
        btn_up = QPushButton("Выше")
        btn_up.clicked.connect(partial(self._move_category_rule, -1))
        btn_down = QPushButton("Ниже")
        btn_down.clicked.connect(partial(self._move_category_rule, 1))
        btn_del = QPushButton("Удалить")
        btn_del.clicked.connect(self._delete_category_rule)
        form.addWidget(self._rule_match, stretch=2)
        form.addWidget(self._rule_kind)
        form.addWidget(self._rule_cat)
        form.addWidget(self._btn_rule_add)
        form.addWidget(self._btn_rule_save)
        form.addWidget(btn_del)
        form.addWidget(btn_up)
        form.addWidget(btn_down)
        cat_l.addLayout(form)
        self._tabs.addTab(cat_w, "Категории")

        # --- Settings tab ---
        set_w = QWidget()
        form_set = QFormLayout(set_w)

        self._theme_combo = QComboBox()
        self._theme_combo.addItem("Тёмная", "dark")
        self._theme_combo.addItem("Светлая", "light")
        th = self._db.get_setting("ui_theme", "dark") or "dark"
        self._theme_combo.blockSignals(True)
        self._theme_combo.setCurrentIndex(0 if th == "dark" else 1)
        self._theme_combo.blockSignals(False)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        form_set.addRow("Тема оформления:", self._theme_combo)

        self._autostart_cb = QCheckBox("Запускать вместе с Windows")
        self._autostart_cb.setChecked(self._db.get_autostart_enabled())
        self._autostart_cb.toggled.connect(self._save_autostart)
        form_set.addRow(self._autostart_cb)

        self._close_to_tray_cb = QCheckBox("Сворачивать в трей при закрытии окна")
        self._close_to_tray_cb.setChecked(
            (self._db.get_setting("close_to_tray", "1") or "1") == "1"
        )
        self._close_to_tray_cb.toggled.connect(
            lambda checked: self._db.set_setting("close_to_tray", "1" if checked else "0")
        )
        self._close_to_tray_cb.setEnabled(self._tray_available)
        form_set.addRow(self._close_to_tray_cb)

        self._afk = QDoubleSpinBox()
        self._afk.setRange(5.0, 3600.0)
        self._afk.setSingleStep(10.0)
        self._afk.setSuffix(" с")
        self._afk.setValue(self._db.get_afk_seconds())
        self._afk.valueChanged.connect(self._save_afk)
        form_set.addRow("Порог «отошёл от ПК» (нет мыши/клавиатуры):", self._afk)

        ex = QGroupBox("Исключить из учёта приложения (имена exe через запятую)")
        ex_l = QVBoxLayout(ex)
        self._excluded = QLineEdit()
        self._excluded.setText(", ".join(sorted(self._db.get_excluded_exes())))
        self._excluded.editingFinished.connect(self._save_excluded)
        ex_l.addWidget(self._excluded)
        form_set.addRow(ex)

        hint = QLabel(
            "Учитывается только активное окно (foreground): при отсутствии ввода дольше порога AFK "
            "время не идёт ни для ПК, ни для приложения. Пока ПК выключен, данные не пишутся.\n"
            f"База данных: {self._db.path}"
        )
        hint.setWordWrap(True)
        form_set.addRow(hint)

        self._tabs.addTab(set_w, "Настройки")

        self._current_period: Period = "week"
        self._apply_period_label()
        self._sync_period_buttons()
        self._refresh_rules_table()
        th_key = th if th in ("dark", "light") else "dark"
        self._reports.apply_chart_theme(th_key)

    def _refresh_rules_table(self) -> None:
        rows = self._db.list_category_rules()
        current_id = self._selected_rule_id()
        self._rules_table.blockSignals(True)
        self._rules_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            rid = int(r["id"])
            it0 = QTableWidgetItem(str(rid))
            it0.setData(Qt.ItemDataRole.UserRole, rid)
            self._rules_table.setItem(i, 0, it0)
            self._rules_table.setItem(i, 1, SortableItem(str(r["priority"])))
            self._rules_table.item(i, 1).setData(Qt.ItemDataRole.UserRole, int(r["priority"]))
            self._rules_table.setItem(i, 2, QTableWidgetItem(r["match_text"]))
            kind_label = "Точное имя exe" if r["match_kind"] == "exact_basename" else "Фрагмент пути"
            kind_item = QTableWidgetItem(kind_label)
            kind_item.setData(Qt.ItemDataRole.UserRole, r["match_kind"])
            self._rules_table.setItem(i, 3, kind_item)
            cat = r["category"]
            self._rules_table.setItem(
                i, 4, QTableWidgetItem(CATEGORY_LABELS_RU.get(cat, cat))
            )
            if current_id == rid:
                self._rules_table.selectRow(i)
        self._rules_table.blockSignals(False)

    def _selected_rule_id(self) -> int | None:
        row = self._rules_table.currentRow()
        if row < 0:
            return None
        it = self._rules_table.item(row, 0)
        if it is None:
            return None
        rid = it.data(Qt.ItemDataRole.UserRole)
        return int(rid) if rid is not None else None

    @Slot()
    def _load_selected_rule(self) -> None:
        row = self._rules_table.currentRow()
        if row < 0:
            return
        match = self._rules_table.item(row, 2)
        kind = self._rules_table.item(row, 3)
        cat = self._rules_table.item(row, 4)
        if match is not None:
            self._rule_match.setText(match.text())
        if kind is not None:
            idx = self._rule_kind.findData(kind.data(Qt.ItemDataRole.UserRole))
            if idx >= 0:
                self._rule_kind.setCurrentIndex(idx)
        if cat is not None:
            for i in range(self._rule_cat.count()):
                if self._rule_cat.itemText(i) == cat.text():
                    self._rule_cat.setCurrentIndex(i)
                    break

    @Slot()
    def _add_category_rule(self) -> None:
        m = self._rule_match.text().strip()
        if not m:
            QMessageBox.warning(self, "Категории", "Введите шаблон.")
            return
        kind = self._rule_kind.currentData()
        cat = self._rule_cat.currentData()
        self._db.add_category_rule(m, str(kind), str(cat))
        self._rule_match.clear()
        self._refresh_rules_table()
        self.refresh_stats(force_reports=True)

    @Slot()
    def _save_category_rule(self) -> None:
        rid = self._selected_rule_id()
        if rid is None:
            return
        m = self._rule_match.text().strip()
        if not m:
            QMessageBox.warning(self, "Категории", "Введите шаблон.")
            return
        self._db.update_category_rule(
            rid, m, str(self._rule_kind.currentData()), str(self._rule_cat.currentData())
        )
        self._refresh_rules_table()
        self.refresh_stats(force_reports=True)

    @Slot()
    def _delete_category_rule(self) -> None:
        row = self._rules_table.currentRow()
        if row < 0:
            return
        it = self._rules_table.item(row, 0)
        if it is None:
            return
        rid = self._selected_rule_id()
        if rid is None:
            return
        self._db.delete_category_rule(rid)
        self._refresh_rules_table()
        self.refresh_stats(force_reports=True)

    def _move_category_rule(self, direction: int) -> None:
        rid = self._selected_rule_id()
        if rid is None:
            return
        self._db.move_category_rule(rid, direction)
        self._refresh_rules_table()
        self.refresh_stats(force_reports=True)

    @Slot()
    def _save_autostart(self) -> None:
        en = self._autostart_cb.isChecked()
        if autostart.set_enabled(en):
            self._db.set_autostart_enabled(en)
            return
        self._autostart_cb.blockSignals(True)
        self._autostart_cb.setChecked(not en)
        self._autostart_cb.blockSignals(False)
        QMessageBox.warning(self, "Автозапуск", "Windows не разрешила изменить автозапуск.")

    def _sync_period_buttons(self) -> None:
        for key, btn in self._period_buttons.items():
            selected = key == self._current_period
            btn.setChecked(selected)
            btn.setProperty("selected", selected)
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    @Slot()
    def _on_theme_changed(self) -> None:
        name = self._theme_combo.currentData()
        if not name:
            return
        self._db.set_setting("ui_theme", str(name))
        app = QApplication.instance()
        if app:
            app.setStyleSheet(load_stylesheet(str(name)))
        sh = app.styleHints() if app else None
        if sh and hasattr(sh, "setColorScheme"):
            try:
                sh.setColorScheme(
                    Qt.ColorScheme.Dark
                    if name == "dark"
                    else Qt.ColorScheme.Light
                )
            except Exception:
                pass
        self._reports.apply_chart_theme(str(name))

    def _set_period(self, p: Period) -> None:
        self._current_period = p
        self._apply_period_label()
        self._sync_period_buttons()
        self.refresh_stats(force_reports=True)

    def _apply_period_label(self) -> None:
        return

    def _period_bounds(self) -> tuple[float, float]:
        if self._current_period == "all":
            ear = self._db.earliest_interval_start()
            return period_range("all", all_start=ear)
        return period_range(self._current_period)

    @Slot()
    def _save_afk(self) -> None:
        self._db.set_afk_seconds(float(self._afk.value()))

    @Slot()
    def _save_excluded(self) -> None:
        raw = self._excluded.text()
        parts = {p.strip().lower() for p in raw.replace(";", ",").split(",") if p.strip()}
        self._db.set_excluded_exes(parts)

    @Slot()
    def _export_csv(self) -> None:
        path, _sel = QFileDialog.getSaveFileName(
            self,
            "Сохранить отчёт CSV",
            "",
            "CSV (*.csv);;Все файлы (*.*)",
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        q_from, q_to = self._period_bounds()
        try:
            export_apps_csv(self._db, q_from, q_to, path, self._last_stats)
        except OSError as e:
            QMessageBox.warning(self, "Экспорт", str(e))

    @Slot()
    def _mark_refresh_dirty(self) -> None:
        self._refresh_dirty = True

    def _refresh_if_dirty(self) -> None:
        if self._refresh_dirty and self.isVisible():
            self.refresh_stats()

    def _on_tab_changed(self, _idx: int) -> None:
        if self._last_stats is not None:
            self._apply_current_stats(force_reports=True)

    @Slot()
    def refresh_stats(self, *, force_reports: bool = False) -> None:
        q_from, q_to = self._period_bounds()
        stats = self._db.period_stats(q_from, q_to)
        self._last_stats = stats
        self._refresh_dirty = False
        self._apply_current_stats(force_reports=force_reports)

    def _filtered_apps(self, stats: PeriodStats) -> list[AppStat]:
        text = self._filter_search.text().strip().lower()
        cat_filter = str(self._filter_cat.currentData() or "")
        out: list[AppStat] = []
        for app in stats.apps:
            cat = app.category or self._db.resolve_category(app.exe_path)
            if cat_filter and cat != cat_filter:
                continue
            disp = friendly_app_name(app.exe_path)
            if text and text not in disp.lower() and text not in app.exe_path.lower():
                continue
            out.append(app)
        return out

    @Slot()
    def _apply_current_stats(self, *, force_reports: bool = False) -> None:
        stats = self._last_stats
        if stats is None:
            return
        apps = self._filtered_apps(stats)

        boot = float(psutil.boot_time())
        session_uptime = max(0.0, time.time() - boot)

        wall_sec = max(0.0, stats.q_to - stats.q_from)
        pc_uptime_sec = stats.estimated_uptime_sec
        denom_sec = pc_uptime_sec if pc_uptime_sec > 0 else wall_sec

        share_pct = 0.0
        if denom_sec > 0 and stats.pc_ms > 0:
            share_pct = min(100.0, 100.0 * (stats.pc_ms / 1000.0) / denom_sec)

        self._kpi_labels["active"].setText(format_duration_ms(stats.pc_ms))
        self._kpi_labels["uptime"].setText(format_duration_seconds(pc_uptime_sec))
        self._kpi_labels["share"].setText(f"{share_pct:.1f}%")
        self._kpi_labels["coverage"].setText(f"{stats.coverage_pct:.1f}%")
        self._kpi_labels["apps"].setText(str(len(stats.apps)))
        self._kpi_labels["session"].setText(format_duration_seconds(session_uptime))

        prev_text = ""
        prev_range = previous_period_range(self._current_period, stats.q_from, stats.q_to)
        if prev_range is not None:
            prev_ms = self._db.total_pc_ms(*prev_range)
            delta_ms = stats.pc_ms - prev_ms
            sign = "+" if delta_ms >= 0 else "-"
            prev_text = f" Сравнение с прошлым периодом: {sign}{format_duration_ms(abs(delta_ms))}."

        self._period_stats.setText(
            f"Календарная длина периода: {format_duration_seconds(wall_sec)}; "
            f"оценка времени работы ПК в этом интервале: {format_duration_seconds(pc_uptime_sec)}. "
            f"Показано приложений: {len(apps)} из {len(stats.apps)}. "
            f"Покрытие приложениями: {stats.coverage_pct:.1f}%."
            f"{prev_text}"
        )

        for i in range(5):
            name_lbl, bar = self._top5_bars[i]
            if i < len(stats.apps) and stats.pc_ms > 0:
                a = stats.apps[i]
                disp = friendly_app_name(a.exe_path)
                name_lbl.setText(disp[:56] + ("…" if len(disp) > 56 else ""))
                pct = min(100, int(round(100.0 * a.active_ms / stats.pc_ms)))
                bar.setValue(pct)
                bar.setFormat(f"{format_duration_ms(a.active_ms)}  ({pct}% от активного времени ПК)")
            else:
                name_lbl.setText("—")
                bar.setValue(0)
                bar.setFormat("—")

        self._fill_apps_table(apps, stats.pc_ms)
        if force_reports or self._tabs.currentWidget() is self._reports:
            self._reports.refresh(stats)

    def _fill_apps_table(self, apps: list[AppStat], pc_ms: float) -> None:
        selected_path = self._selected_app_path()
        scroll_value = self._table.verticalScrollBar().value()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(apps))
        fm = QFontMetrics(self._table.font())
        path_col_w = self._table.columnWidth(4)
        elide_w = max(160, path_col_w - 24) if path_col_w > 0 else 420

        for i, a in enumerate(apps):
            disp = friendly_app_name(a.exe_path)
            it0 = QTableWidgetItem(disp)
            it0.setIcon(app_icon_for_exe(a.exe_path))
            it0.setToolTip(f"{disp}\n{a.exe_path}")
            it0.setData(Qt.ItemDataRole.UserRole, a.exe_path)
            self._table.setItem(i, 0, it0)

            cat = a.category or self._db.resolve_category(a.exe_path)
            it_cat = QTableWidgetItem(CATEGORY_LABELS_RU.get(cat, cat))
            it_cat.setToolTip(cat)
            it_cat.setBackground(QBrush(QColor(CATEGORY_COLORS.get(cat, "#94a3b8"))))
            self._table.setItem(i, 1, it_cat)

            it_active = SortableItem(format_duration_ms(a.active_ms))
            it_active.setData(Qt.ItemDataRole.UserRole, float(a.active_ms))
            it_active.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(i, 2, it_active)

            pct = 100.0 * a.active_ms / pc_ms if pc_ms > 0 else 0.0
            it_pct = SortableItem(f"{pct:.1f}%")
            it_pct.setData(Qt.ItemDataRole.UserRole, pct)
            it_pct.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(i, 3, it_pct)

            path_show = fm.elidedText(
                a.exe_path, Qt.TextElideMode.ElideMiddle, elide_w
            )
            it1 = QTableWidgetItem(path_show)
            it1.setToolTip(a.exe_path)
            self._table.setItem(i, 4, it1)

            if selected_path and selected_path == a.exe_path:
                self._table.selectRow(i)
        self._table.setSortingEnabled(True)
        self._table.verticalScrollBar().setValue(scroll_value)

    def _selected_app_path(self) -> str | None:
        row = self._table.currentRow()
        if row < 0:
            return None
        it = self._table.item(row, 0)
        if it is None:
            return None
        path = it.data(Qt.ItemDataRole.UserRole)
        return str(path) if path else None

    @Slot()
    def _create_rule_from_selected_app(self) -> None:
        path = self._selected_app_path()
        if not path:
            return
        apps = self._last_stats.apps if self._last_stats is not None else []
        app = next((a for a in apps if a.exe_path == path), None)
        if app is None:
            return
        self._rule_match.setText(app.exe_name)
        self._rule_kind.setCurrentIndex(self._rule_kind.findData("exact_basename"))
        idx = self._rule_cat.findData(app.category or OTHER)
        if idx >= 0:
            self._rule_cat.setCurrentIndex(idx)
        self._db.add_category_rule(app.exe_name, "exact_basename", app.category or OTHER)
        self._refresh_rules_table()
        self.refresh_stats(force_reports=True)
        self._tabs.setCurrentWidget(self._tabs.widget(2))

    def closeEvent(self, event: QCloseEvent) -> None:
        close_to_tray = (self._db.get_setting("close_to_tray", "1") or "1") == "1"
        if self._tray_available and close_to_tray:
            event.ignore()
            if (self._db.get_setting("first_close_to_tray_notice_seen", "0") or "0") != "1":
                self._db.set_setting("first_close_to_tray_notice_seen", "1")
                QMessageBox.information(
                    self,
                    "PC Stat",
                    "Окно скрыто, трекер продолжает работать в области уведомлений.",
                )
            self.hide()
            return
        event.accept()
