from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from pc_stat_win.categories import BROWSER, DEVTOOLS
from pc_stat_win.db import AppStat
from pc_stat_win.ui.app_table import (
    CATEGORY_ROLE,
    FILTER_DELAY_MS,
    SORT_ROLE,
    AppFilterProxyModel,
    AppTableColumn,
    AppTableModel,
)
from pc_stat_win.ui.styles import ACCENT, render_stylesheet, semantic_palette
from pc_stat_win.ui.theme_manager import ThemeManager
from pc_stat_win.ui.reports_tab import ReportsTab


class UiInfrastructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.rows = [
            AppStat("slow.exe", r"C:\Apps\slow.exe", 9_000.0, DEVTOOLS),
            AppStat("fast.exe", r"C:\Apps\fast.exe", 500.0, BROWSER),
        ]

    def test_theme_template_renders_semantic_palettes(self) -> None:
        light = render_stylesheet("light")
        dark = render_stylesheet("dark")

        for rendered in (light, dark):
            self.assertNotIn("${", rendered)
            self.assertIn("background-color: transparent", rendered)
            self.assertIn("border: 2px solid #2563EB", rendered)
            self.assertIn("min-height: 36px", rendered)
            self.assertIn("rgba(", rendered)

        self.assertEqual(semantic_palette("light")["accent"], ACCENT)
        self.assertEqual(semantic_palette("dark")["accent"], ACCENT)
        self.assertNotEqual(light, dark)

    def test_model_exposes_numeric_and_category_roles(self) -> None:
        model = AppTableModel(self.rows, total_ms=10_000.0)

        active = model.index(0, AppTableColumn.ACTIVE)
        category = model.index(0, AppTableColumn.CATEGORY)
        share = model.index(0, AppTableColumn.SHARE)
        self.assertEqual(active.data(SORT_ROLE), 9_000.0)
        self.assertEqual(category.data(CATEGORY_ROLE), DEVTOOLS)
        self.assertEqual(share.data(Qt.ItemDataRole.DisplayRole), "90.0%")

        parent_owned = AppTableModel(self.app)
        self.assertIs(parent_owned.parent(), self.app)

    def test_proxy_sorts_numbers_and_filters_immediately(self) -> None:
        model = AppTableModel(self.rows, total_ms=10_000.0)
        proxy = AppFilterProxyModel()
        proxy.setSourceModel(model)
        proxy.sort(AppTableColumn.ACTIVE, Qt.SortOrder.AscendingOrder)

        first = proxy.index(0, AppTableColumn.ACTIVE)
        self.assertEqual(first.data(SORT_ROLE), 500.0)

        self.assertEqual(FILTER_DELAY_MS, 120)
        proxy.set_filter_text("slow apps")
        self.assertEqual(proxy.rowCount(), 1)
        proxy.set_category(BROWSER)
        self.assertEqual(proxy.rowCount(), 0)
        proxy.set_filter_text("fast")
        self.assertEqual(proxy.rowCount(), 1)

    def test_theme_manager_applies_explicit_modes(self) -> None:
        manager = ThemeManager(self.app, "light")
        self.assertEqual(manager.resolved_theme, "light")
        self.assertIn(semantic_palette("light")["window"], self.app.styleSheet())

        manager.set_mode("dark")
        self.assertEqual(manager.resolved_theme, "dark")
        self.assertIn(semantic_palette("dark")["window"], self.app.styleSheet())

    def test_report_series_compression_preserves_full_total(self) -> None:
        source = [(str(index), float(index)) for index in range(200)]
        compressed = ReportsTab._compress_series(source, 62)
        self.assertLessEqual(len(compressed), 62)
        self.assertEqual(sum(value for _label, value in compressed), 19_900.0)
        self.assertEqual(compressed[-1][0], "199")


if __name__ == "__main__":
    unittest.main()
