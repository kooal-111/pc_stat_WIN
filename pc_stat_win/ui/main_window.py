from __future__ import annotations

import time
from functools import partial

import psutil
from PySide6.QtCore import QSize, Qt, Slot
from PySide6.QtGui import QCloseEvent, QFont, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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

from pc_stat_win.categories import CATEGORY_LABELS_RU
from pc_stat_win.collector import UsageCollector
from pc_stat_win.db import Database
from pc_stat_win.exe_metadata import friendly_app_name
from pc_stat_win.export import export_apps_csv
from pc_stat_win.formatting import format_duration_ms, format_duration_seconds
from pc_stat_win.periods import Period, period_range
from pc_stat_win.ui.icons import app_icon_for_exe
from pc_stat_win.ui.reports_tab import ReportsTab
from pc_stat_win.ui.styles import load_stylesheet


class MainWindow(QMainWindow):
    def __init__(
        self,
        db: Database,
        collector: UsageCollector,
        *,
        window_icon: QIcon | None = None,
    ) -> None:
        super().__init__()
        self._db = db
        self._collector = collector
        self.setWindowTitle("PC Stat — активность")
        if window_icon is not None and not window_icon.isNull():
            self.setWindowIcon(window_icon)
        self.setMinimumSize(920, 640)
        self._build()
        self._collector.tick_done.connect(self.refresh_stats)
        self.refresh_stats()

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        tabs = QTabWidget()
        root.addWidget(tabs)

        # --- Stats tab ---
        stats_w = QWidget()
        stats_layout = QVBoxLayout(stats_w)

        top = QHBoxLayout()
        top.addWidget(QLabel("Период:"))
        self._period = QLineEdit()
        self._period.setReadOnly(True)
        self._period.setPlaceholderText("выберите пресет справа")
        top.addWidget(self._period, stretch=1)

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
            b.setAutoDefault(False)
            b.clicked.connect(partial(self._set_period, key))
            top.addWidget(b)

        self._btn_export = QPushButton("Экспорт CSV…")
        self._btn_export.setObjectName("btnExport")
        self._btn_export.clicked.connect(self._export_csv)
        top.addWidget(self._btn_export)

        stats_layout.addLayout(top)

        card = QFrame()
        card.setObjectName("card")
        card_l = QVBoxLayout(card)
        self._summary = QLabel()
        self._summary.setObjectName("summaryLabel")
        self._summary.setWordWrap(True)
        f = QFont()
        f.setPointSize(11)
        self._summary.setFont(f)
        card_l.addWidget(self._summary)
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

        self._table = QTableWidget(0, 4)
        self._table.setObjectName("appsTable")
        self._table.setAlternatingRowColors(True)
        self._table.setIconSize(QSize(28, 28))
        self._table.setShowGrid(False)
        self._table.verticalHeader().setVisible(False)
        self._table.setHorizontalHeaderLabels(
            ["Приложение", "Путь", "Категория", "Активно (фокус + ввод)"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        stats_layout.addWidget(self._table)

        tabs.addTab(stats_w, "Статистика")

        # --- Reports ---
        self._reports = ReportsTab(self._db)
        tabs.addTab(self._reports, "Отчёты")

        # --- Categories ---
        cat_w = QWidget()
        cat_l = QVBoxLayout(cat_w)
        cat_l.addWidget(
            QLabel(
                "Правила сопоставляются сверху вниз (приоритет). "
                "«Точное имя exe» — только basename; «Фрагмент пути» — подстрока в полном пути."
            )
        )
        self._rules_table = QTableWidget(0, 4)
        self._rules_table.setHorizontalHeaderLabels(["ID", "Шаблон", "Тип", "Категория"])
        self._rules_table.hideColumn(0)
        self._rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
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
        btn_add = QPushButton("Добавить правило")
        btn_add.clicked.connect(self._add_category_rule)
        btn_del = QPushButton("Удалить выбранное")
        btn_del.clicked.connect(self._delete_category_rule)
        form.addWidget(self._rule_match, stretch=2)
        form.addWidget(self._rule_kind)
        form.addWidget(self._rule_cat)
        form.addWidget(btn_add)
        form.addWidget(btn_del)
        cat_l.addLayout(form)
        tabs.addTab(cat_w, "Категории")

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
            "Учитывается только активное окно (foreground). "
            "Время без ввода дольше порога не идёт в «активное» ни для ПК, ни для приложений.\n"
            f"База данных: {self._db.path}"
        )
        hint.setWordWrap(True)
        form_set.addRow(hint)

        tabs.addTab(set_w, "Настройки")

        self._current_period: Period = "week"
        self._apply_period_label()
        self._refresh_rules_table()
        th_key = th if th in ("dark", "light") else "dark"
        self._reports.apply_chart_theme(th_key)

    def _refresh_rules_table(self) -> None:
        rows = self._db.list_category_rules()
        self._rules_table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            rid = int(r["id"])
            it0 = QTableWidgetItem(str(rid))
            it0.setData(Qt.ItemDataRole.UserRole, rid)
            self._rules_table.setItem(i, 0, it0)
            self._rules_table.setItem(i, 1, QTableWidgetItem(r["match_text"]))
            self._rules_table.setItem(i, 2, QTableWidgetItem(r["match_kind"]))
            cat = r["category"]
            self._rules_table.setItem(
                i, 3, QTableWidgetItem(CATEGORY_LABELS_RU.get(cat, cat))
            )

    @Slot()
    def _add_category_rule(self) -> None:
        m = self._rule_match.text().strip()
        if not m:
            QMessageBox.warning(self, "Категории", "Введите шаблон.")
            return
        kind = self._rule_kind.currentData()
        cat = self._rule_cat.currentData()
        self._db.add_category_rule(m, str(kind), str(cat), priority=100)
        self._rule_match.clear()
        self._refresh_rules_table()
        self.refresh_stats()

    @Slot()
    def _delete_category_rule(self) -> None:
        row = self._rules_table.currentRow()
        if row < 0:
            return
        it = self._rules_table.item(row, 0)
        if it is None:
            return
        rid = it.data(Qt.ItemDataRole.UserRole)
        if rid is None:
            return
        self._db.delete_category_rule(int(rid))
        self._refresh_rules_table()
        self.refresh_stats()

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
        self.refresh_stats()

    def _apply_period_label(self) -> None:
        labels = {
            "today": "Сегодня (с полуночи)",
            "week": "Текущая неделя (с понедельника)",
            "month": "Текущий месяц (с 1-го числа)",
            "year": "Текущий календарный год (с 1 января)",
            "all": "Всё время (от первой записи в базе)",
        }
        self._period.setText(labels.get(self._current_period, ""))

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
            export_apps_csv(self._db, q_from, q_to, path)
        except OSError as e:
            QMessageBox.warning(self, "Экспорт", str(e))

    @Slot()
    def refresh_stats(self) -> None:
        q_from, q_to = self._period_bounds()
        pc_ms = self._db.total_pc_ms(q_from, q_to)
        apps = self._db.totals_by_app(q_from, q_to)

        boot = float(psutil.boot_time())
        session_uptime = max(0.0, time.time() - boot)

        wall_sec = max(0.0, q_to - q_from)
        share_pct = 0.0
        if wall_sec > 0 and pc_ms > 0:
            share_pct = min(100.0, 100.0 * (pc_ms / 1000.0) / wall_sec)

        self._summary.setText(
            f"Время с загрузки Windows (сейчас): {format_duration_seconds(session_uptime)}.\n"
            f"Активное время за выбранный период (есть ввод мыши/клавиатуры, без AFK): "
            f"{format_duration_ms(pc_ms)}.\n"
            f"Окно в фокусе без ввода не считается активным использованием."
        )

        self._period_stats.setText(
            f"Длительность выбранного периода: {format_duration_seconds(wall_sec)}. "
            f"Приложений в таблице: {len(apps)}. "
            f"Доля активного времени от длины периода: {share_pct:.1f}% "
            f"(отношение суммарного активного времени к длительности периода)."
        )

        for i in range(5):
            name_lbl, bar = self._top5_bars[i]
            if i < len(apps) and pc_ms > 0:
                a = apps[i]
                disp = friendly_app_name(a.exe_path)
                name_lbl.setText(disp[:48] + ("…" if len(disp) > 48 else ""))
                pct = min(100, int(round(100.0 * a.active_ms / pc_ms)))
                bar.setValue(pct)
                bar.setFormat(f"{format_duration_ms(a.active_ms)}  ({pct}% от активного времени ПК)")
            else:
                name_lbl.setText("—")
                bar.setValue(0)
                bar.setFormat("—")

        self._table.setRowCount(len(apps))
        fm = QFontMetrics(self._table.font())
        path_col_w = self._table.columnWidth(1)
        elide_w = max(160, path_col_w - 24) if path_col_w > 0 else 420

        for i, a in enumerate(apps):
            disp = friendly_app_name(a.exe_path)
            it0 = QTableWidgetItem(disp)
            it0.setIcon(app_icon_for_exe(a.exe_path))
            it0.setToolTip(f"{disp}\n{a.exe_path}")
            self._table.setItem(i, 0, it0)

            path_show = fm.elidedText(
                a.exe_path, Qt.TextElideMode.ElideMiddle, elide_w
            )
            it1 = QTableWidgetItem(path_show)
            it1.setToolTip(a.exe_path)
            self._table.setItem(i, 1, it1)

            cat = self._db.resolve_category(a.exe_path)
            it_cat = QTableWidgetItem(CATEGORY_LABELS_RU.get(cat, cat))
            it_cat.setToolTip(cat)
            self._table.setItem(i, 2, it_cat)

            it2 = QTableWidgetItem(format_duration_ms(a.active_ms))
            it2.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(i, 3, it2)

        self._reports.refresh(q_from, q_to)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()
