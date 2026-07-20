from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QColor, QPalette
from PySide6.QtWidgets import QApplication, QBoxLayout, QMessageBox, QScrollArea

from pc_stat_win.categories import BROWSER
from pc_stat_win.collector import UsageCollector
from pc_stat_win.db import AppStat, Database, PeriodStats
from pc_stat_win.periods import period_range
from pc_stat_win.ui.main_window import MainWindow
from pc_stat_win.ui.styles import render_stylesheet, semantic_palette
from pc_stat_win.ui.theme_manager import ThemeManager


def make_stats(count: int = 48, *, reverse: bool = False) -> PeriodStats:
    apps = [
        AppStat(
            f"application-{index:02d}.exe",
            rf"C:\Program Files\Very Long Product Name {index:02d}\application-{index:02d}.exe",
            float((count - index) * 60_000),
            BROWSER,
        )
        for index in range(count)
    ]
    if reverse:
        apps.reverse()
    total = sum(app.active_ms for app in apps)
    return PeriodStats(
        q_from=1_000.0,
        q_to=4_600.0,
        pc_ms=total,
        apps=apps,
        by_category={BROWSER: total},
        chart_mode="hour",
        chart_series=[(f"{hour:02d}:00", 300_000.0 + hour) for hour in range(24)],
        estimated_uptime_sec=3_600.0,
        previous_pc_ms=total * 0.8,
        chart_by_category={
            BROWSER: [300_000.0 + hour for hour in range(24)],
        },
    )


class MainWindowV130Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="pc_stat_ui_v130_")
        self.db = Database(Path(self.tmp.name) / "data.sqlite")
        self.collector = UsageCollector(self.db, boot_time_provider=lambda: 900.0)
        self.window = MainWindow(self.db, self.collector, tray_available=False)

    def tearDown(self) -> None:
        self.window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.window._tray_available = False
        self.window.close()
        self.app.processEvents()
        self.collector.stop()
        self.db.close()
        self.tmp.cleanup()

    def test_compact_geometry_sidebar_and_stats_height(self) -> None:
        self.window.resize(760, 520)
        self.window.show()
        self.app.processEvents()

        self.assertEqual(self.window.minimumWidth(), 760)
        self.assertEqual(self.window.minimumHeight(), 520)
        self.assertEqual(self.window.width(), 760)
        self.assertEqual(self.window.height(), 520)
        self.assertTrue(self.window._sidebar_compact)
        self.assertEqual(self.window._sidebar.width(), 64)
        self.assertFalse(self.window._top_surface.isVisible())
        self.assertGreaterEqual(self.window._table.height(), 220)
        for label, button in zip(self.window._nav_labels, self.window._nav_buttons):
            self.assertEqual(button.text(), "")
            self.assertEqual(button.toolTip(), label)
            self.assertEqual(button.accessibleName(), label)

    def test_categories_stack_and_outer_pages_do_not_overflow(self) -> None:
        self.window.resize(760, 520)
        self.window.show()
        self.window._set_page(self.window.PAGE_CATEGORIES)
        self.app.processEvents()

        self.assertEqual(
            self.window._categories_layout.direction(),
            QBoxLayout.Direction.TopToBottom,
        )
        self.assertGreater(self.window._categories_scroll.verticalScrollBar().maximum(), 0)
        for scroll in self.window.findChildren(QScrollArea):
            if not scroll.isVisible():
                continue
            self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
            self.assertLessEqual(scroll.widget().width(), scroll.viewport().width() + 1)

        self.window.resize(1280, 800)
        self.app.processEvents()
        self.assertEqual(
            self.window._categories_layout.direction(),
            QBoxLayout.Direction.LeftToRight,
        )

    def test_model_refresh_preserves_selection_and_scroll(self) -> None:
        self.window.resize(1180, 620)
        self.window.show()
        self.window._apply_stats(make_stats())
        self.app.processEvents()

        source_index = self.window._app_model.index(21, 0)
        proxy_index = self.window._app_proxy.mapFromSource(source_index)
        self.window._table.setCurrentIndex(proxy_index)
        self.window._table.selectRow(proxy_index.row())
        target_path = self.window._selected_app().exe_path
        vertical = self.window._table.verticalScrollBar()
        vertical.setValue(max(1, vertical.maximum() // 2))
        expected_vertical = vertical.value()
        horizontal = self.window._table.horizontalScrollBar()
        expected_horizontal = horizontal.value()

        self.window._apply_stats(make_stats(reverse=True))
        self.app.processEvents()

        self.assertEqual(self.window._selected_app().exe_path, target_path)
        self.assertEqual(vertical.value(), expected_vertical)
        self.assertEqual(horizontal.value(), expected_horizontal)

    def test_status_repolish_contract_and_tooltip_cleanup(self) -> None:
        self.collector.error_occurred.emit("database is locked")
        self.assertEqual(self.window._collector_status.objectName(), "statusError")
        self.assertEqual(self.window._collector_status.toolTip(), "database is locked")

        self.window._apply_stats(make_stats(2))
        self.assertEqual(self.window._collector_status.objectName(), "statusError")
        self.collector.recovered.emit()
        self.assertEqual(self.window._collector_status.objectName(), "statusOk")
        self.assertEqual(self.window._collector_status.toolTip(), "")

    def test_window_title_privacy_setting_defaults_off_and_reloads(self) -> None:
        self.assertFalse(self.window._collect_window_titles_cb.isChecked())
        self.collector.reload_settings = Mock()

        self.window._collect_window_titles_cb.setChecked(True)

        self.assertEqual(self.db.get_setting("collect_window_titles"), "1")
        self.collector.reload_settings.assert_called_once_with()

    def test_retention_control_and_history_delete_are_available(self) -> None:
        self.assertEqual(self.window._retention_combo.currentData(), 0)
        self.assertTrue(self.window._delete_history_btn.isEnabled())

        index = self.window._retention_combo.findData(90)
        with patch.object(self.collector, "flush", return_value=True):
            self.window._retention_combo.setCurrentIndex(index)
        self.assertEqual(self.db.get_retention_days(), 90)

    def test_rule_actions_follow_selection_and_confirm_delete(self) -> None:
        self.db.add_category_rule("first.exe", "exact_basename", BROWSER)
        self.db.add_category_rule("second.exe", "exact_basename", BROWSER)
        self.window._selected_rule = None
        self.window._refresh_rules_table()

        self.assertTrue(self.window._rule_add_btn.property("primary"))
        self.assertFalse(self.window._rule_save_btn.isEnabled())
        self.assertFalse(self.window._rule_delete_btn.isEnabled())
        self.window._rules_table.selectRow(0)
        self.app.processEvents()
        self.assertTrue(self.window._rule_save_btn.isEnabled())
        self.assertFalse(self.window._rule_up_btn.isEnabled())
        self.assertTrue(self.window._rule_down_btn.isEnabled())

        before = len(self.db.list_category_rules())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
            self.window._delete_category_rule()
        self.assertEqual(len(self.db.list_category_rules()), before)

        self.window._rules_table.selectRow(self.window._rules_table.rowCount() - 1)
        self.app.processEvents()
        self.assertTrue(self.window._rule_up_btn.isEnabled())
        self.assertFalse(self.window._rule_down_btn.isEnabled())

    def test_report_page_rebuilds_chart_once(self) -> None:
        self.window._last_stats = make_stats(4)
        self.window._refresh_dirty = False
        refresh_chart = Mock()
        self.window._reports._refresh_chart = refresh_chart

        self.window._set_page(self.window.PAGE_REPORTS)
        self.app.processEvents()
        self.assertEqual(refresh_chart.call_count, 1)

    def test_report_period_navigation_never_enters_future(self) -> None:
        self.window._set_period("month")
        self.window._set_page(self.window.PAGE_REPORTS)
        self.window._shift_report_period(-1)
        self.assertEqual(self.window._period_offset, -1)
        self.assertTrue(self.window._reports._next_button.isEnabled())

        historical = self.window._period_bounds()
        current = period_range("month")
        self.assertLessEqual(historical[1], current[0])

        self.window._shift_report_period(1)
        self.window._shift_report_period(1)
        self.assertEqual(self.window._period_offset, 0)
        self.assertFalse(self.window._reports._next_button.isEnabled())

    def test_reports_use_day_week_month_year_copy(self) -> None:
        self.window._set_page(self.window.PAGE_REPORTS)
        self.window.resize(1180, 760)
        self.app.processEvents()
        labels = [button.text() for button in self.window._period_buttons.values()]
        self.assertEqual(labels[:4], ["День", "Неделя", "Месяц", "Год"])
        self.assertNotIn("7 дн.", labels)
        self.assertNotIn("30 дн.", labels)

    def test_report_chart_uses_transparent_surface_without_legend(self) -> None:
        reports = self.window._reports
        reports.set_active(True)
        reports.refresh(make_stats(4))
        if reports._chart_failed:
            self.skipTest("QtCharts is unavailable")

        self.assertFalse(reports._chart.isBackgroundVisible())
        self.assertFalse(reports._chart.isPlotAreaBackgroundVisible())
        self.assertFalse(reports._chart.legend().isVisible())
        reports.refresh(make_stats(4))
        self.app.processEvents()
        self.assertEqual(len(reports._chart.axes()), 2)

    def test_close_without_close_to_tray_requests_application_quit(self) -> None:
        self.window._tray_available = True
        quit_requests: list[bool] = []
        tray_requests: list[bool] = []
        self.window.quit_requested.connect(lambda: quit_requests.append(True))
        self.window.close_to_tray_requested.connect(lambda: tray_requests.append(True))

        self.db.set_setting("first_close_to_tray_notice_seen", "1")
        self.db.set_setting("close_to_tray", "1")
        tray_event = QCloseEvent()
        self.window.closeEvent(tray_event)
        self.assertTrue(tray_event.isAccepted())
        self.assertEqual(quit_requests, [])
        self.assertEqual(tray_requests, [True])

        self.db.set_setting("close_to_tray", "0")
        event = QCloseEvent()
        self.window.closeEvent(event)
        self.assertTrue(event.isAccepted())
        self.assertEqual(quit_requests, [True])
        self.assertEqual(tray_requests, [True])

        self.window._tray_available = False
        self.window.closeEvent(QCloseEvent())
        self.assertEqual(quit_requests, [True])


class ThemeV130Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_semantic_qpalette_and_native_checkbox_state(self) -> None:
        manager = ThemeManager(self.app, "light")
        colors = semantic_palette("light")
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.Window),
            QColor(colors["window"]),
        )
        self.assertEqual(colors["success"], "#137333")
        self.assertNotIn("QCheckBox::indicator", render_stylesheet("light"))

        manager.set_mode("dark")
        self.assertEqual(
            self.app.palette().color(QPalette.ColorRole.WindowText),
            QColor(semantic_palette("dark")["text"]),
        )


if __name__ == "__main__":
    unittest.main()
