from __future__ import annotations

import base64
import logging
import sqlite3
import time
from functools import partial
from pathlib import Path

import psutil
from PySide6.QtCore import QByteArray, QSize, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import (
    QCloseEvent,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from pc_stat_win import autostart
from pc_stat_win.categories import CATEGORY_LABELS_RU, OTHER
from pc_stat_win.collector import UsageCollector
from pc_stat_win.config import UI_REFRESH_INTERVAL_MS
from pc_stat_win.db import (
    AppStat,
    Database,
    PeriodStats,
    RETENTION_DAY_OPTIONS,
    normalize_rule_match_text,
)
from pc_stat_win.exe_metadata import friendly_app_name
from pc_stat_win.export import export_apps_csv
from pc_stat_win.formatting import format_duration_ms, format_duration_seconds
from pc_stat_win.periods import Period, period_range, previous_period_range
from pc_stat_win.ui.app_table import AppFilterProxyModel, AppTableModel, CategoryDotDelegate
from pc_stat_win.ui.reports_tab import ReportsTab


LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    theme_changed = Signal(str)
    close_to_tray_requested = Signal()
    quit_requested = Signal()

    PAGE_STATS = 0
    PAGE_REPORTS = 1
    PAGE_CATEGORIES = 2
    PAGE_SETTINGS = 3

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
        self._kpi_frames: list[QFrame] = []
        self._kpi_columns = 0
        self._selected_rule: int | None = None
        self._sidebar_compact = False
        self._categories_compact = False
        self._collector_error_detail: str | None = None
        self._period_offset = 0
        self._maintenance_busy = False
        self._busy_cursor_active = False

        self.setWindowTitle("PC Stat — активность")
        if window_icon is not None and not window_icon.isNull():
            self.setWindowIcon(window_icon)
        self.setMinimumSize(760, 520)
        self.resize(1180, 760)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, tray_available)

        saved_period = self._setting_value("ui_period", "week")
        self._current_period: Period = (
            saved_period if saved_period in ("today", "week", "month", "year", "all") else "week"
        )
        self._build()
        self._restore_window_state()

        self._collector.tick_done.connect(self._mark_refresh_dirty)
        self._collector.error_occurred.connect(self._on_collector_error)
        self._collector.recovered.connect(self._on_collector_recovered)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(max(10_000, UI_REFRESH_INTERVAL_MS))
        self._refresh_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._refresh_timer.timeout.connect(self._refresh_if_dirty)
        self._refresh_timer.start()

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(120)
        self._search_timer.timeout.connect(self._apply_filters)
        self.refresh_stats(force_reports=self._stack.currentIndex() == self.PAGE_REPORTS)

    def _build(self) -> None:
        central = QWidget()
        central.setObjectName("windowSurface")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        self._sidebar = QFrame()
        self._sidebar.setObjectName("navigationSurface")
        self._sidebar.setFixedWidth(188)
        side = QVBoxLayout(self._sidebar)
        side.setContentsMargins(12, 14, 12, 12)
        side.setSpacing(6)

        self._brand = QLabel("PC Stat")
        self._brand.setObjectName("brandTitle")
        side.addWidget(self._brand)
        self._brand_subtitle = QLabel("Фокус и активность")
        self._brand_subtitle.setObjectName("secondaryText")
        side.addWidget(self._brand_subtitle)
        side.addSpacing(16)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_buttons: list[QPushButton] = []
        self._nav_labels: list[str] = []
        nav_specs = [
            ("Статистика", QStyle.StandardPixmap.SP_ComputerIcon),
            ("Отчёты", QStyle.StandardPixmap.SP_FileDialogDetailedView),
            ("Категории", QStyle.StandardPixmap.SP_DirIcon),
            ("Настройки", QStyle.StandardPixmap.SP_FileDialogContentsView),
        ]
        for index, (text, icon_kind) in enumerate(nav_specs):
            button = QPushButton(text)
            button.setProperty("navigation", True)
            button.setCheckable(True)
            button.setIcon(self.style().standardIcon(icon_kind))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.setAccessibleDescription(f"Открыть раздел «{text}»")
            button.clicked.connect(partial(self._set_page, index))
            self._nav_group.addButton(button, index)
            self._nav_buttons.append(button)
            self._nav_labels.append(text)
            side.addWidget(button)
        side.addStretch(1)

        self._collector_status = QLabel("●  Сбор активен")
        self._collector_status.setObjectName("statusOk")
        side.addWidget(self._collector_status)
        self._session_label = QLabel()
        self._session_label.setObjectName("secondaryText")
        self._session_label.setWordWrap(True)
        side.addWidget(self._session_label)
        root.addWidget(self._sidebar)

        content = QVBoxLayout()
        content.setSpacing(12)
        header = QFrame()
        header.setObjectName("glassSurface")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(14, 10, 14, 10)
        self._page_title = QLabel("Статистика")
        self._page_title.setObjectName("pageTitle")
        header_layout.addWidget(self._page_title)
        header_layout.addStretch(1)

        self._period_host = QWidget()
        self._period_host.setObjectName("periodSegmentHost")
        period_layout = QHBoxLayout(self._period_host)
        period_layout.setContentsMargins(2, 2, 2, 2)
        period_layout.setSpacing(2)
        self._period_group = QButtonGroup(self)
        self._period_group.setExclusive(True)
        self._period_buttons: dict[Period, QPushButton] = {}
        for label, key in (
            ("Сегодня", "today"),
            ("Неделя", "week"),
            ("Месяц", "month"),
            ("Год", "year"),
            ("Всё", "all"),
        ):
            button = QPushButton(label)
            button.setProperty("segment", True)
            button.setCheckable(True)
            button.clicked.connect(partial(self._set_period, key))
            self._period_group.addButton(button)
            self._period_buttons[key] = button
            period_layout.addWidget(button)
        header_layout.addWidget(self._period_host)

        self._btn_export = QPushButton("Экспорт")
        self._btn_export.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self._btn_export.clicked.connect(self._export_csv)
        header_layout.addWidget(self._btn_export)
        content.addWidget(header)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_stats_page())
        self._reports = ReportsTab(self._db)
        self._reports.navigate_requested.connect(self._shift_report_period)
        self._reports.current_period_requested.connect(self._return_to_current_period)
        self._report_previous_shortcut = QShortcut(
            QKeySequence("Ctrl+Left"), self._reports
        )
        self._report_previous_shortcut.activated.connect(
            partial(self._shift_report_period, -1)
        )
        self._report_next_shortcut = QShortcut(
            QKeySequence("Ctrl+Right"), self._reports
        )
        self._report_next_shortcut.activated.connect(
            partial(self._shift_report_period, 1)
        )
        self._stack.addWidget(self._reports)
        self._stack.addWidget(self._build_categories_page())
        self._stack.addWidget(self._build_settings_page())
        self._stack.currentChanged.connect(self._on_page_changed)
        content.addWidget(self._stack, 1)
        root.addLayout(content, 1)

        try:
            saved_page = int(self._setting_value("ui_page", "0"))
        except ValueError:
            saved_page = 0
        saved_page = max(0, min(self._stack.count() - 1, saved_page))
        self._stack.setCurrentIndex(saved_page)
        self._nav_buttons[saved_page].setChecked(True)
        self._sync_period_buttons()
        self._on_page_changed(saved_page)
        self._apply_responsive_layout()

    def _build_stats_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("pageContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        filters = QFrame()
        filters.setObjectName("glassSurface")
        filter_layout = QHBoxLayout(filters)
        filter_layout.setContentsMargins(12, 10, 12, 10)
        self._filter_search = QLineEdit()
        self._filter_search.setClearButtonEnabled(True)
        self._filter_search.setPlaceholderText("Поиск по приложению или пути")
        self._filter_search.textChanged.connect(lambda _text: self._search_timer.start())
        filter_layout.addWidget(self._filter_search, 1)
        self._filter_cat = QComboBox()
        self._filter_cat.addItem("Все категории", "")
        for key, label in CATEGORY_LABELS_RU.items():
            self._filter_cat.addItem(label, key)
        self._filter_cat.currentIndexChanged.connect(self._apply_filters)
        filter_layout.addWidget(self._filter_cat)
        self._btn_rule_from_app = QPushButton("Новое правило")
        self._btn_rule_from_app.setEnabled(False)
        self._btn_rule_from_app.clicked.connect(self._prepare_rule_from_selected_app)
        filter_layout.addWidget(self._btn_rule_from_app)
        layout.addWidget(filters)

        self._kpi_host = QFrame()
        self._kpi_host.setObjectName("glassSurface")
        self._kpi_grid = QGridLayout(self._kpi_host)
        self._kpi_grid.setContentsMargins(12, 12, 12, 12)
        self._kpi_grid.setSpacing(8)
        self._kpi_labels: dict[str, QLabel] = {}
        for key, title in (
            ("active", "Активное время"),
            ("uptime", "Работа ПК"),
            ("share", "Доля активности"),
            ("coverage", "Покрытие"),
            ("apps", "Приложений"),
            ("session", "Текущая сессия"),
        ):
            item = QFrame()
            item.setObjectName("metricBlock")
            item_layout = QVBoxLayout(item)
            item_layout.setContentsMargins(10, 7, 10, 7)
            name = QLabel(title)
            name.setObjectName("secondaryText")
            value = QLabel("—")
            value.setObjectName("metricValue")
            item_layout.addWidget(name)
            item_layout.addWidget(value)
            self._kpi_frames.append(item)
            self._kpi_labels[key] = value
        self._reflow_kpis(3)
        layout.addWidget(self._kpi_host)

        self._top_surface = QFrame()
        self._top_surface.setObjectName("glassSurface")
        top_layout = QVBoxLayout(self._top_surface)
        top_layout.setContentsMargins(14, 12, 14, 12)
        top_title = QLabel("Топ приложений")
        top_title.setObjectName("sectionTitle")
        top_layout.addWidget(top_title)
        self._top_rows: list[tuple[QLabel, QLabel, QProgressBar]] = []
        for _index in range(5):
            row = QHBoxLayout()
            name = QLabel("—")
            name.setMinimumWidth(160)
            duration = QLabel("—")
            duration.setObjectName("secondaryText")
            duration.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            duration.setMinimumWidth(90)
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(8)
            row.addWidget(name)
            row.addWidget(bar, 1)
            row.addWidget(duration)
            top_layout.addLayout(row)
            self._top_rows.append((name, duration, bar))
        layout.addWidget(self._top_surface)

        table_surface = QFrame()
        table_surface.setObjectName("glassSurface")
        table_layout = QVBoxLayout(table_surface)
        table_layout.setContentsMargins(8, 8, 8, 8)
        self._app_model = AppTableModel(self)
        self._app_proxy = AppFilterProxyModel(self)
        self._app_proxy.setSourceModel(self._app_model)
        self._table = QTableView()
        self._table.setModel(self._app_proxy)
        self._table.setAlternatingRowColors(True)
        self._table.setShowGrid(False)
        self._table.setWordWrap(False)
        self._table.setSortingEnabled(True)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setMinimumHeight(220)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(42)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            self._table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.setItemDelegateForColumn(1, CategoryDotDelegate(self._table))
        self._table.selectionModel().selectionChanged.connect(
            lambda *_args: self._btn_rule_from_app.setEnabled(self._selected_app() is not None)
        )
        table_layout.addWidget(self._table)
        layout.addWidget(table_surface, 1)
        return page

    def _build_categories_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        page = QWidget()
        page.setObjectName("pageContent")
        layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        self._categories_layout = layout
        self._categories_inner = page
        self._categories_scroll = scroll

        self._rules_table_surface = QFrame()
        self._rules_table_surface.setObjectName("glassSurface")
        table_layout = QVBoxLayout(self._rules_table_surface)
        table_layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Правила классификации")
        title.setObjectName("sectionTitle")
        table_layout.addWidget(title)
        self._rules_table = QTableWidget(0, 5)
        self._rules_table.setHorizontalHeaderLabels(
            ["ID", "Приоритет", "Шаблон", "Тип", "Категория"]
        )
        self._rules_table.hideColumn(0)
        self._rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._rules_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._rules_table.setShowGrid(False)
        self._rules_table.setMinimumHeight(260)
        self._rules_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rules_table.verticalHeader().setVisible(False)
        self._rules_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._rules_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._rules_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._rules_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._rules_table.itemSelectionChanged.connect(self._load_selected_rule)
        table_layout.addWidget(self._rules_table)
        layout.addWidget(self._rules_table_surface, 2)

        self._rule_editor = QFrame()
        self._rule_editor.setObjectName("glassSurface")
        self._rule_editor.setMinimumWidth(310)
        self._rule_editor.setMinimumHeight(300)
        editor_layout = QVBoxLayout(self._rule_editor)
        editor_layout.setContentsMargins(16, 14, 16, 14)
        editor_title = QLabel("Редактор правила")
        editor_title.setObjectName("sectionTitle")
        editor_layout.addWidget(editor_title)
        self._rule_match = QLineEdit()
        self._rule_match.setPlaceholderText("chrome.exe или фрагмент пути")
        editor_layout.addWidget(QLabel("Шаблон"))
        editor_layout.addWidget(self._rule_match)
        self._rule_kind = QComboBox()
        self._rule_kind.addItem("Точное имя exe", "exact_basename")
        self._rule_kind.addItem("Фрагмент пути", "path_contains")
        editor_layout.addWidget(QLabel("Тип совпадения"))
        editor_layout.addWidget(self._rule_kind)
        self._rule_cat = QComboBox()
        for key, label in CATEGORY_LABELS_RU.items():
            self._rule_cat.addItem(label, key)
        editor_layout.addWidget(QLabel("Категория"))
        editor_layout.addWidget(self._rule_cat)
        editor_layout.addSpacing(8)

        save_row = QHBoxLayout()
        self._rule_add_btn = QPushButton("Добавить")
        self._rule_add_btn.setProperty("primary", True)
        self._rule_add_btn.clicked.connect(self._add_category_rule)
        self._rule_save_btn = QPushButton("Сохранить")
        self._rule_save_btn.clicked.connect(self._save_category_rule)
        save_row.addWidget(self._rule_add_btn)
        save_row.addWidget(self._rule_save_btn)
        editor_layout.addLayout(save_row)

        icon_row = QHBoxLayout()
        self._rule_up_btn = self._icon_button(QStyle.StandardPixmap.SP_ArrowUp, "Поднять правило")
        self._rule_up_btn.clicked.connect(partial(self._move_category_rule, -1))
        self._rule_down_btn = self._icon_button(QStyle.StandardPixmap.SP_ArrowDown, "Опустить правило")
        self._rule_down_btn.clicked.connect(partial(self._move_category_rule, 1))
        self._rule_delete_btn = self._icon_button(QStyle.StandardPixmap.SP_TrashIcon, "Удалить правило")
        self._rule_delete_btn.setProperty("danger", True)
        self._rule_delete_btn.clicked.connect(self._delete_category_rule)
        icon_row.addWidget(self._rule_up_btn)
        icon_row.addWidget(self._rule_down_btn)
        icon_row.addStretch(1)
        icon_row.addWidget(self._rule_delete_btn)
        editor_layout.addLayout(icon_row)
        editor_layout.addStretch(1)
        layout.addWidget(self._rule_editor, 1)
        scroll.setWidget(page)
        self._refresh_rules_table()
        return scroll

    def _build_settings_page(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("pageContent")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 8, 16)
        layout.setSpacing(12)

        appearance = QFrame()
        appearance.setObjectName("glassSurface")
        appearance_form = QFormLayout(appearance)
        appearance_form.setContentsMargins(16, 14, 16, 14)
        self._theme_combo = QComboBox()
        self._theme_combo.addItem("Как в Windows", "system")
        self._theme_combo.addItem("Тёмная", "dark")
        self._theme_combo.addItem("Светлая", "light")
        theme = self._db.get_setting("ui_theme", "system") or "system"
        theme_index = self._theme_combo.findData(theme)
        self._theme_combo.setCurrentIndex(max(0, theme_index))
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        appearance_form.addRow("Оформление", self._theme_combo)
        layout.addWidget(appearance)

        behavior = QFrame()
        behavior.setObjectName("glassSurface")
        behavior_form = QFormLayout(behavior)
        behavior_form.setContentsMargins(16, 14, 16, 14)
        self._autostart_cb = QCheckBox("Запускать вместе с Windows")
        self._autostart_cb.setChecked(self._db.get_autostart_enabled())
        self._autostart_cb.toggled.connect(self._save_autostart)
        behavior_form.addRow(self._autostart_cb)
        self._close_to_tray_cb = QCheckBox("Закрывать окно в область уведомлений")
        self._close_to_tray_cb.setChecked(
            (self._db.get_setting("close_to_tray", "1") or "1") == "1"
        )
        self._close_to_tray_cb.setEnabled(self._tray_available)
        self._close_to_tray_cb.toggled.connect(self._save_close_to_tray)
        behavior_form.addRow(self._close_to_tray_cb)
        self._collect_window_titles_cb = QCheckBox("Сохранять заголовки окон")
        self._collect_window_titles_cb.setAccessibleName("Сохранять заголовки окон")
        self._collect_window_titles_cb.setChecked(
            (self._db.get_setting("collect_window_titles", "0") or "0") == "1"
        )
        self._collect_window_titles_cb.toggled.connect(self._save_collect_window_titles)
        behavior_form.addRow(self._collect_window_titles_cb)
        self._retention_combo = QComboBox()
        retention_labels = {
            0: "Без ограничения",
            30: "30 дней",
            90: "90 дней",
            180: "180 дней",
            365: "1 год",
        }
        for days in RETENTION_DAY_OPTIONS:
            self._retention_combo.addItem(retention_labels[days], days)
        retention_index = self._retention_combo.findData(self._db.get_retention_days())
        self._retention_combo.setCurrentIndex(max(0, retention_index))
        self._retention_combo.currentIndexChanged.connect(self._save_retention)
        behavior_form.addRow("Хранить статистику", self._retention_combo)
        self._afk = QDoubleSpinBox()
        self._afk.setRange(5.0, 3600.0)
        self._afk.setSingleStep(10.0)
        self._afk.setSuffix(" с")
        self._afk.setValue(self._db.get_afk_seconds())
        self._afk.editingFinished.connect(self._save_afk)
        behavior_form.addRow("Порог AFK", self._afk)
        layout.addWidget(behavior)

        exclusions = QFrame()
        exclusions.setObjectName("glassSurface")
        exclusions_layout = QVBoxLayout(exclusions)
        exclusions_layout.setContentsMargins(16, 14, 16, 14)
        title = QLabel("Исключённые приложения")
        title.setObjectName("sectionTitle")
        exclusions_layout.addWidget(title)
        hint = QLabel("Имена exe через запятую. Эти приложения не попадут в статистику.")
        hint.setObjectName("secondaryText")
        hint.setWordWrap(True)
        exclusions_layout.addWidget(hint)
        self._excluded = QLineEdit()
        self._excluded.setText(", ".join(sorted(self._db.get_excluded_exes())))
        self._excluded.editingFinished.connect(self._save_excluded)
        exclusions_layout.addWidget(self._excluded)
        layout.addWidget(exclusions)

        location_surface = QFrame()
        location_surface.setObjectName("glassSurface")
        location_layout = QHBoxLayout(location_surface)
        location_layout.setContentsMargins(16, 12, 16, 12)
        self._db_location = QLabel(f"База данных: {self._db.path}")
        self._db_location.setObjectName("secondaryText")
        self._db_location.setWordWrap(True)
        self._db_location.setMinimumWidth(0)
        self._db_location.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._db_location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._db_location.setToolTip(str(self._db.path))
        location_layout.addWidget(self._db_location, 1)
        self._open_db_folder_btn = QPushButton("Открыть папку")
        self._open_db_folder_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        )
        self._open_db_folder_btn.setAccessibleName("Открыть папку базы данных")
        self._open_db_folder_btn.clicked.connect(self._open_database_folder)
        location_layout.addWidget(self._open_db_folder_btn)
        layout.addWidget(location_surface)

        privacy_surface = QFrame()
        privacy_surface.setObjectName("glassSurface")
        privacy_layout = QHBoxLayout(privacy_surface)
        privacy_layout.setContentsMargins(16, 12, 16, 12)
        privacy_text = QLabel(
            "Удаляет интервалы активности и историю загрузок. "
            "Настройки и правила категорий сохраняются."
        )
        privacy_text.setObjectName("secondaryText")
        privacy_text.setWordWrap(True)
        privacy_layout.addWidget(privacy_text, 1)
        self._delete_history_btn = QPushButton("Удалить статистику")
        self._delete_history_btn.setProperty("danger", True)
        self._delete_history_btn.clicked.connect(self._delete_history)
        privacy_layout.addWidget(self._delete_history_btn)
        layout.addWidget(privacy_surface)
        layout.addStretch(1)
        scroll.setWidget(page)
        return scroll

    def _open_database_folder(self) -> None:
        folder = Path(self._db.path).resolve().parent
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(self, "База данных", "Не удалось открыть папку базы данных.")

    def _icon_button(self, icon: QStyle.StandardPixmap, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(36, 36)
        return button

    def _set_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)

    def _on_page_changed(self, index: int) -> None:
        titles = ("Статистика", "Отчёты", "Категории", "Настройки")
        self._page_title.setText(titles[index])
        for button_index, button in enumerate(self._nav_buttons):
            button.setChecked(button_index == index)
        self._period_host.setVisible(index in (self.PAGE_STATS, self.PAGE_REPORTS))
        self._btn_export.setVisible(index in (self.PAGE_STATS, self.PAGE_REPORTS))
        self._reports.set_active(index == self.PAGE_REPORTS)
        self._sync_period_labels()
        self._set_setting_best_effort("ui_page", str(index), "UI page")
        if index == self.PAGE_REPORTS:
            self._reports.set_period_context(self._current_period, self._period_offset)
            if self._refresh_dirty:
                self.refresh_stats(force_reports=True)
            elif self._last_stats is not None and self._last_stats.chart_series:
                self._reports.refresh(
                    self._last_stats,
                    self._current_period,
                    self._period_offset,
                )
            else:
                self.refresh_stats(force_reports=True)
        elif index == self.PAGE_CATEGORIES:
            self._refresh_rules_table()
        elif self._period_offset != 0:
            self._period_offset = 0
            self._refresh_dirty = True
            self._reports.set_period_context(self._current_period, 0)
            if index == self.PAGE_STATS:
                self.refresh_stats()

    def _set_period(self, period: Period) -> None:
        self._current_period = period
        self._period_offset = 0
        self._set_setting_best_effort("ui_period", period, "UI period")
        self._sync_period_buttons()
        self._reports.set_period_context(period, 0)
        self.refresh_stats(force_reports=self._stack.currentIndex() == self.PAGE_REPORTS)

    def _shift_report_period(self, direction: int) -> None:
        if self._stack.currentIndex() != self.PAGE_REPORTS or self._current_period == "all":
            return
        offset = min(0, self._period_offset + (-1 if direction < 0 else 1))
        if offset == self._period_offset:
            return
        self._period_offset = offset
        self._reports.set_period_context(self._current_period, offset)
        self.refresh_stats(force_reports=True)

    def _return_to_current_period(self) -> None:
        if self._period_offset == 0:
            return
        self._period_offset = 0
        self._reports.set_period_context(self._current_period, 0)
        self.refresh_stats(force_reports=True)

    def _sync_period_buttons(self) -> None:
        for key, button in self._period_buttons.items():
            selected = key == self._current_period
            button.setChecked(selected)
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)

    def _period_bounds(self) -> tuple[float, float]:
        if self._current_period == "all":
            return period_range("all", all_start=self._db.earliest_interval_start())
        return period_range(self._current_period, offset=self._period_offset)

    @Slot()
    def refresh_stats(self, *, force_reports: bool = False) -> None:
        try:
            self._collector.flush("stats")
            q_from, q_to = self._period_bounds()
            previous = previous_period_range(self._current_period, q_from, q_to)
            reports_visible = force_reports or self._stack.currentIndex() == self.PAGE_REPORTS
            stats = self._db.period_stats(
                q_from,
                q_to,
                previous_range=previous,
                include_chart=reports_visible,
                chart_period=self._current_period if reports_visible else None,
            )
        except Exception as exc:
            LOGGER.warning("Unable to refresh statistics", exc_info=True)
            self._set_collector_status(False, str(exc))
            return
        self._last_stats = stats
        self._refresh_dirty = False
        self._apply_stats(stats)
        if force_reports or self._stack.currentIndex() == self.PAGE_REPORTS:
            self._reports.refresh(stats, self._current_period, self._period_offset)

    def _apply_stats(self, stats: PeriodStats) -> None:
        wall_seconds = max(0.0, stats.q_to - stats.q_from)
        uptime_seconds = stats.estimated_uptime_sec
        denominator = uptime_seconds if uptime_seconds > 0 else wall_seconds
        share = (
            min(100.0, 100.0 * (stats.pc_ms / 1000.0) / denominator)
            if denominator > 0
            else 0.0
        )
        session = max(0.0, time.time() - float(psutil.boot_time()))
        self._kpi_labels["active"].setText(format_duration_ms(stats.pc_ms))
        self._kpi_labels["uptime"].setText(format_duration_seconds(uptime_seconds))
        self._kpi_labels["share"].setText(f"{share:.1f}%")
        self._kpi_labels["coverage"].setText(f"{stats.coverage_pct:.1f}%")
        self._kpi_labels["apps"].setText(str(len(stats.apps)))
        self._kpi_labels["session"].setText(format_duration_seconds(session))
        self._session_label.setText(f"Сессия: {format_duration_seconds(session)}")
        if self._collector_error_detail:
            self._set_collector_status(False, self._collector_error_detail)
        else:
            self._set_collector_status(True)

        for index, (name, duration, bar) in enumerate(self._top_rows):
            if index >= len(stats.apps) or stats.pc_ms <= 0:
                name.setText("—")
                duration.setText("—")
                bar.setValue(0)
                continue
            app = stats.apps[index]
            display = friendly_app_name(app.exe_path)
            name.setText(display)
            name.setToolTip(display)
            duration.setText(format_duration_ms(app.active_ms))
            bar.setValue(max(0, min(1000, int(round(1000 * app.active_ms / stats.pc_ms)))))
        selected_path, vertical_scroll, horizontal_scroll = self._capture_app_table_state()
        self._app_model.set_rows(stats.apps, total_ms=stats.pc_ms)
        self._restore_app_table_state(selected_path, vertical_scroll, horizontal_scroll)

    def _set_collector_status(self, healthy: bool, details: str = "") -> None:
        self._collector_status.setText("●  Сбор активен" if healthy else "●  Ошибка обновления")
        self._collector_status.setObjectName("statusOk" if healthy else "statusError")
        self._collector_status.setToolTip("" if healthy else details)
        style = self._collector_status.style()
        style.unpolish(self._collector_status)
        style.polish(self._collector_status)
        self._collector_status.update()

    @Slot(str)
    def _on_collector_error(self, details: str) -> None:
        self._collector_error_detail = details or "Неизвестная ошибка сбора"
        self._set_collector_status(False, self._collector_error_detail)

    @Slot()
    def _on_collector_recovered(self) -> None:
        self._collector_error_detail = None
        self._set_collector_status(True)

    def _capture_app_table_state(self) -> tuple[str | None, int, int]:
        selected = self._selected_app()
        return (
            selected.exe_path if selected is not None else None,
            self._table.verticalScrollBar().value(),
            self._table.horizontalScrollBar().value(),
        )

    def _restore_app_table_state(
        self,
        selected_path: str | None,
        vertical_scroll: int,
        horizontal_scroll: int,
    ) -> None:
        if selected_path:
            for row in range(self._app_model.rowCount()):
                app = self._app_model.row_at(row)
                if isinstance(app, AppStat) and app.exe_path == selected_path:
                    proxy_index = self._app_proxy.mapFromSource(self._app_model.index(row, 0))
                    if proxy_index.isValid():
                        self._table.setCurrentIndex(proxy_index)
                        self._table.selectRow(proxy_index.row())
                    break
        self._table.verticalScrollBar().setValue(vertical_scroll)
        self._table.horizontalScrollBar().setValue(horizontal_scroll)
        self._btn_rule_from_app.setEnabled(self._selected_app() is not None)

    @Slot()
    def _mark_refresh_dirty(self) -> None:
        self._refresh_dirty = True

    def _refresh_if_dirty(self) -> None:
        if self._refresh_dirty and self.isVisible():
            self.refresh_stats(force_reports=self._stack.currentIndex() == self.PAGE_REPORTS)

    def _apply_filters(self) -> None:
        self._app_proxy.set_filter_text(self._filter_search.text())
        self._app_proxy.set_category(str(self._filter_cat.currentData() or ""))

    def _selected_app(self) -> AppStat | None:
        indexes = self._table.selectionModel().selectedRows()
        if not indexes:
            return None
        source_index = self._app_proxy.mapToSource(indexes[0])
        app = self._app_model.row_at(source_index.row())
        return app if isinstance(app, AppStat) else None

    def _prepare_rule_from_selected_app(self) -> None:
        app = self._selected_app()
        if app is None:
            return
        self._selected_rule = None
        self._rules_table.clearSelection()
        self._rules_table.setCurrentCell(-1, -1)
        self._update_rule_actions()
        self._rule_match.setText(app.exe_name)
        self._rule_kind.setCurrentIndex(self._rule_kind.findData("exact_basename"))
        category_index = self._rule_cat.findData(app.category or OTHER)
        if category_index >= 0:
            self._rule_cat.setCurrentIndex(category_index)
        self._set_page(self.PAGE_CATEGORIES)
        self._rule_match.setFocus()

    def _selected_rule_id(self) -> int | None:
        row = self._rules_table.currentRow()
        if row < 0:
            return self._selected_rule
        item = self._rules_table.item(row, 0)
        return int(item.text()) if item is not None else self._selected_rule

    def _refresh_rules_table(self) -> None:
        rows = self._db.list_category_rules()
        selected = self._selected_rule_id()
        self._rules_table.blockSignals(True)
        self._rules_table.setRowCount(len(rows))
        selected_row = -1
        for row_index, rule in enumerate(rows):
            rule_id = int(rule["id"])
            values = (
                str(rule_id),
                str(rule["priority"]),
                str(rule["match_text"]),
                "Точное имя exe" if rule["match_kind"] == "exact_basename" else "Фрагмент пути",
                CATEGORY_LABELS_RU.get(rule["category"], rule["category"]),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 3:
                    item.setData(Qt.ItemDataRole.UserRole, rule["match_kind"])
                if column == 4:
                    item.setData(Qt.ItemDataRole.UserRole, rule["category"])
                self._rules_table.setItem(row_index, column, item)
            if selected == rule_id:
                selected_row = row_index
        self._rules_table.blockSignals(False)
        if selected_row >= 0:
            self._rules_table.selectRow(selected_row)
        else:
            self._selected_rule = None
            self._rules_table.clearSelection()
            self._rules_table.setCurrentCell(-1, -1)
        self._update_rule_actions()

    def _load_selected_rule(self) -> None:
        row = self._rules_table.currentRow()
        if row < 0:
            self._selected_rule = None
            self._update_rule_actions()
            return
        id_item = self._rules_table.item(row, 0)
        if id_item is None:
            return
        self._selected_rule = int(id_item.text())
        self._rule_match.setText(self._rules_table.item(row, 2).text())
        kind = self._rules_table.item(row, 3).data(Qt.ItemDataRole.UserRole)
        category = self._rules_table.item(row, 4).data(Qt.ItemDataRole.UserRole)
        self._rule_kind.setCurrentIndex(self._rule_kind.findData(kind))
        self._rule_cat.setCurrentIndex(self._rule_cat.findData(category))
        self._update_rule_actions()

    def _update_rule_actions(self) -> None:
        row = self._rules_table.currentRow()
        count = self._rules_table.rowCount()
        valid = row >= 0 and row < count and self._selected_rule_id() is not None
        self._rule_save_btn.setEnabled(valid)
        self._rule_delete_btn.setEnabled(valid)
        self._rule_up_btn.setEnabled(valid and row > 0)
        self._rule_down_btn.setEnabled(valid and row < count - 1)

    def _rule_values(self) -> tuple[str, str, str] | None:
        text = self._rule_match.text().strip()
        kind = str(self._rule_kind.currentData() or "")
        category = str(self._rule_cat.currentData() or "")
        if not text or not kind or not category:
            QMessageBox.warning(self, "Правило", "Заполните шаблон, тип и категорию.")
            return None
        return text, kind, category

    def _rule_duplicate_exists(
        self,
        text: str,
        kind: str,
        *,
        exclude_rule_id: int | None = None,
    ) -> bool:
        normalized = normalize_rule_match_text(text, kind)
        for rule in self._db.list_category_rules():
            if exclude_rule_id is not None and int(rule["id"]) == exclude_rule_id:
                continue
            if rule["match_kind"] != kind:
                continue
            existing = normalize_rule_match_text(str(rule["match_text"]), kind)
            if existing == normalized:
                return True
        return False

    def _show_duplicate_rule_message(self) -> None:
        QMessageBox.information(
            self,
            "Правило",
            "Правило с таким шаблоном уже существует.",
        )

    def _add_category_rule(self) -> None:
        values = self._rule_values()
        if values is None:
            return
        text, kind, category = values
        try:
            if self._rule_duplicate_exists(text, kind):
                self._show_duplicate_rule_message()
                return
            self._selected_rule = self._db.add_category_rule(text, kind, category)
        except sqlite3.IntegrityError:
            self._show_duplicate_rule_message()
            return
        except Exception as exc:
            LOGGER.warning("Unable to add category rule", exc_info=True)
            QMessageBox.warning(self, "Правило", f"Не удалось добавить правило.\n\n{exc}")
            return
        self._refresh_rules_table()
        self.refresh_stats()

    def _save_category_rule(self) -> None:
        rule_id = self._selected_rule_id()
        values = self._rule_values()
        if rule_id is None or values is None:
            return
        text, kind, category = values
        try:
            if self._rule_duplicate_exists(text, kind, exclude_rule_id=rule_id):
                self._show_duplicate_rule_message()
                return
            self._db.update_category_rule(rule_id, text, kind, category)
        except sqlite3.IntegrityError:
            self._show_duplicate_rule_message()
            return
        except Exception as exc:
            LOGGER.warning("Unable to save category rule", exc_info=True)
            QMessageBox.warning(self, "Правило", f"Не удалось сохранить правило.\n\n{exc}")
            return
        self._selected_rule = rule_id
        self._refresh_rules_table()
        self.refresh_stats()

    def _delete_category_rule(self) -> None:
        rule_id = self._selected_rule_id()
        if rule_id is None:
            return
        answer = QMessageBox.question(
            self,
            "Удалить правило",
            "Удалить выбранное правило классификации?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._db.delete_category_rule(rule_id)
        self._selected_rule = None
        self._refresh_rules_table()
        self.refresh_stats()

    def _move_category_rule(self, direction: int) -> None:
        rule_id = self._selected_rule_id()
        if rule_id is None:
            return
        self._db.move_category_rule(rule_id, direction)
        self._selected_rule = rule_id
        self._refresh_rules_table()
        self.refresh_stats()

    @Slot()
    def _save_autostart(self) -> None:
        enabled = self._autostart_cb.isChecked()
        if autostart.set_enabled(enabled):
            self._db.set_autostart_enabled(enabled)
            return
        self._autostart_cb.blockSignals(True)
        self._autostart_cb.setChecked(not enabled)
        self._autostart_cb.blockSignals(False)
        QMessageBox.warning(self, "Автозапуск", "Windows не разрешила изменить автозапуск.")

    def _save_close_to_tray(self, checked: bool) -> None:
        if self._set_setting_best_effort(
            "close_to_tray",
            "1" if checked else "0",
            "close-to-tray preference",
        ):
            return
        self._close_to_tray_cb.blockSignals(True)
        self._close_to_tray_cb.setChecked(self._setting_value("close_to_tray", "1") == "1")
        self._close_to_tray_cb.blockSignals(False)
        QMessageBox.warning(
            self,
            "Настройки",
            "Не удалось сохранить поведение кнопки закрытия.",
        )

    def _save_afk(self) -> None:
        self._db.set_afk_seconds(float(self._afk.value()))
        self._collector.reload_settings()

    def _save_collect_window_titles(self, enabled: bool) -> None:
        if not self._begin_maintenance("Обновление приватности"):
            return
        try:
            self._db.set_collect_window_titles(enabled)
            self._collector.reload_settings()
        except Exception as exc:
            LOGGER.warning("Unable to update window-title privacy setting", exc_info=True)
            self._collect_window_titles_cb.blockSignals(True)
            self._collect_window_titles_cb.setChecked(self._db.get_collect_window_titles())
            self._collect_window_titles_cb.blockSignals(False)
            QMessageBox.warning(
                self,
                "Конфиденциальность",
                f"Не удалось полностью применить настройку.\n\n{exc}",
            )
        finally:
            self._end_maintenance()

    def _save_retention(self) -> None:
        if not self._begin_maintenance("Очистка старых данных"):
            return
        days = int(self._retention_combo.currentData() or 0)
        deleted = 0
        try:
            if not self._collector.flush("retention"):
                raise RuntimeError("не удалось сохранить текущий интервал")
            self._db.set_retention_days(days)
            deleted = self._db.apply_retention_policy()
        except Exception as exc:
            LOGGER.warning("Unable to apply retention policy", exc_info=True)
            QMessageBox.warning(self, "Срок хранения", str(exc))
            return
        finally:
            self._end_maintenance()
        if deleted:
            self.refresh_stats(force_reports=self._stack.currentIndex() == self.PAGE_REPORTS)

    def _delete_history(self) -> None:
        answer = QMessageBox.warning(
            self,
            "Удалить всю статистику",
            "Все интервалы активности будут безвозвратно удалены. "
            "Настройки и правила категорий сохранятся.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._begin_maintenance("Удаление статистики"):
            return
        try:
            self._collector.clear_history()
        except Exception as exc:
            QMessageBox.critical(self, "Удаление статистики", str(exc))
            return
        finally:
            self._end_maintenance()
        self.refresh_stats(force_reports=self._stack.currentIndex() == self.PAGE_REPORTS)

    def _save_excluded(self) -> None:
        values = {
            part.strip().lower()
            for part in self._excluded.text().replace(";", ",").split(",")
            if part.strip()
        }
        self._db.set_excluded_exes(values)
        self._collector.reload_settings()

    def _on_theme_changed(self) -> None:
        mode = str(self._theme_combo.currentData() or "system")
        self._set_setting_best_effort("ui_theme", mode, "UI theme")
        self.theme_changed.emit(mode)

    def apply_theme(self, resolved_theme: str) -> None:
        self._reports.apply_chart_theme(resolved_theme)

    def _export_csv(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт CSV", "", "CSV (*.csv);;Все файлы (*.*)"
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            if not self._collector.flush("export"):
                raise RuntimeError("Не удалось сохранить текущие данные. Экспорт отменён.")
            q_from, q_to = self._period_bounds()
            stats = self._db.period_stats(
                q_from,
                q_to,
                previous_range=previous_period_range(self._current_period, q_from, q_to),
                include_chart=False,
            )
            export_apps_csv(self._db, q_from, q_to, path, stats)
        except sqlite3.Error as exc:
            LOGGER.warning("Unable to read statistics for CSV export", exc_info=True)
            QMessageBox.warning(
                self,
                "Экспорт",
                f"Не удалось прочитать статистику из базы.\n\n{exc}",
            )
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Экспорт", str(exc))
        except Exception as exc:
            LOGGER.warning("Unexpected CSV export failure", exc_info=True)
            QMessageBox.warning(self, "Экспорт", f"Не удалось создать CSV.\n\n{exc}")

    def _reflow_kpis(self, columns: int) -> None:
        if self._kpi_columns == columns:
            return
        self._kpi_columns = columns
        for index, frame in enumerate(self._kpi_frames):
            self._kpi_grid.addWidget(frame, index // columns, index % columns)

    def _apply_responsive_layout(self) -> None:
        if not hasattr(self, "_sidebar"):
            return

        compact_sidebar = self.width() < 980
        if compact_sidebar != self._sidebar_compact:
            self._sidebar_compact = compact_sidebar
            self._sidebar.setFixedWidth(64 if compact_sidebar else 188)
            self._brand.setVisible(not compact_sidebar)
            self._brand_subtitle.setVisible(not compact_sidebar)
            self._collector_status.setVisible(not compact_sidebar)
            self._session_label.setVisible(not compact_sidebar)
            for label, button in zip(self._nav_labels, self._nav_buttons):
                button.setText("" if compact_sidebar else label)
                button.setProperty("compactNavigation", compact_sidebar)
                button.style().unpolish(button)
                button.style().polish(button)

        short_window = self.height() < 700
        self._top_surface.setVisible(not short_window)
        self._table.setMinimumHeight(240 if short_window else 220)
        self._table.setColumnHidden(4, compact_sidebar)

        compact_categories = self.width() < 1080
        if compact_categories != self._categories_compact:
            self._categories_compact = compact_categories
            direction = (
                QBoxLayout.Direction.TopToBottom
                if compact_categories
                else QBoxLayout.Direction.LeftToRight
            )
            self._categories_layout.setDirection(direction)
            self._rule_editor.setMinimumWidth(0 if compact_categories else 310)
            self._categories_inner.setMinimumHeight(590 if compact_categories else 0)
            self._rules_table.setColumnHidden(1, compact_categories)

        self._sync_period_labels()
        if compact_sidebar:
            self._btn_export.setText("")
            self._btn_export.setToolTip("Экспортировать CSV")
            self._btn_export.setAccessibleName("Экспортировать CSV")
        else:
            self._btn_export.setText("Экспорт")

    def _sync_period_labels(self) -> None:
        if not hasattr(self, "_period_buttons") or not hasattr(self, "_stack"):
            return
        reports_page = self._stack.currentIndex() == self.PAGE_REPORTS
        compact = getattr(self, "_sidebar_compact", False)
        if reports_page:
            labels = (
                ("День", "Нед.", "Мес.", "Год", "Всё")
                if compact
                else ("День", "Неделя", "Месяц", "Год", "Всё")
            )
        else:
            labels = (
                ("Сегодня", "Нед.", "Мес.", "Год", "Всё")
                if compact
                else ("Сегодня", "Неделя", "Месяц", "Год", "Всё")
            )
        for button, label in zip(self._period_buttons.values(), labels):
            button.setText(label)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_kpi_grid"):
            self._reflow_kpis(6 if self.width() >= 1320 else 3)
            self._apply_responsive_layout()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._refresh_dirty:
            QTimer.singleShot(0, self.refresh_stats)

    def _setting_value(self, key: str, default: str) -> str:
        try:
            return self._db.get_setting(key, default) or default
        except Exception:
            LOGGER.warning("Unable to read setting %s", key, exc_info=True)
            return default

    def _set_setting_best_effort(self, key: str, value: str, label: str) -> bool:
        try:
            self._db.set_setting(key, value)
        except Exception:
            LOGGER.warning("Unable to save %s", label, exc_info=True)
            return False
        return True

    def _maintenance_controls(self) -> list[QWidget]:
        names = (
            "_collect_window_titles_cb",
            "_retention_combo",
            "_delete_history_btn",
        )
        return [
            widget
            for widget in (getattr(self, name, None) for name in names)
            if isinstance(widget, QWidget)
        ]

    def _begin_maintenance(self, status_text: str) -> bool:
        if self._maintenance_busy:
            return False
        self._maintenance_busy = True
        for widget in self._maintenance_controls():
            widget.setEnabled(False)
        self._collector_status.setText(f"●  {status_text}")
        self._collector_status.setObjectName("statusOk")
        self._collector_status.setToolTip("")
        style = self._collector_status.style()
        style.unpolish(self._collector_status)
        style.polish(self._collector_status)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._busy_cursor_active = True
        QApplication.processEvents()
        return True

    def _end_maintenance(self) -> None:
        if self._busy_cursor_active:
            QApplication.restoreOverrideCursor()
            self._busy_cursor_active = False
        self._maintenance_busy = False
        for widget in self._maintenance_controls():
            widget.setEnabled(True)
        if self._collector_error_detail:
            self._set_collector_status(False, self._collector_error_detail)
        else:
            self._set_collector_status(True)

    def _save_window_state(self) -> None:
        try:
            geometry = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
            self._db.set_setting("ui_geometry", geometry)
            self._db.set_setting("ui_page", str(self._stack.currentIndex()))
            self._db.set_setting("ui_period", self._current_period)
        except Exception:
            LOGGER.warning("Unable to save window state", exc_info=True)

    def _restore_window_state(self) -> None:
        encoded = self._setting_value("ui_geometry", "")
        if not encoded:
            return
        try:
            self.restoreGeometry(QByteArray.fromBase64(encoded.encode("ascii")))
        except (ValueError, TypeError):
            pass

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_window_state()
        close_to_tray = self._setting_value("close_to_tray", "1") == "1"
        if self._tray_available and close_to_tray:
            if self._setting_value("first_close_to_tray_notice_seen", "0") != "1":
                self._set_setting_best_effort(
                    "first_close_to_tray_notice_seen",
                    "1",
                    "first close-to-tray notice",
                )
                QMessageBox.information(
                    self,
                    "PC Stat",
                    "Окно будет закрыто, а сбор продолжится в области уведомлений.",
                )
            event.accept()
            self.close_to_tray_requested.emit()
            return
        event.accept()
        if self._tray_available:
            self.quit_requested.emit()
