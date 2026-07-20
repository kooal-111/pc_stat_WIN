from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
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

    def test_packaged_icon_has_windows_size_layers(self) -> None:
        icon_path = (
            Path(__file__).resolve().parents[1]
            / "pc_stat_win"
            / "assets"
            / "app.ico"
        )
        raw = icon_path.read_bytes()
        reserved, image_type, count = struct.unpack_from("<HHH", raw)
        self.assertEqual((reserved, image_type), (0, 1))
        sizes = []
        for index in range(count):
            width, height = struct.unpack_from("<BB", raw, 6 + index * 16)
            sizes.append(
                (256 if width == 0 else width, 256 if height == 0 else height)
            )
        self.assertEqual(
            sizes,
            [
                (16, 16),
                (20, 20),
                (24, 24),
                (32, 32),
                (40, 40),
                (48, 48),
                (64, 64),
                (96, 96),
                (128, 128),
                (256, 256),
            ],
        )
        png = QImage(str(icon_path.with_suffix(".png")))
        self.assertFalse(png.isNull())
        self.assertEqual((png.width(), png.height()), (512, 512))
        self.assertEqual(png.pixelColor(0, 0).alpha(), 0)
        self.assertEqual(png.pixelColor(256, 256).alpha(), 255)

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
        self.assertIn("QMainWindow[windowMaterial=\"mica\"]", light)
        self.assertIn("rgba(238, 244, 250, 248)", light)
        self.assertNotIn(
            'QMainWindow[windowMaterial="mica"] {\n    background-color: transparent;',
            light,
        )

    def test_light_theme_text_controls_and_scrollbar_meet_contrast_targets(self) -> None:
        colors = semantic_palette("light")

        def luminance(value: str) -> float:
            color = QColor(value)
            channels = (color.redF(), color.greenF(), color.blueF())
            linear = [
                channel / 12.92
                if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
                for channel in channels
            ]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(first: str, second: str) -> float:
            values = sorted((luminance(first), luminance(second)), reverse=True)
            return (values[0] + 0.05) / (values[1] + 0.05)

        surface = colors["surface"]
        for key in ("text", "text_muted", "text_disabled"):
            self.assertGreaterEqual(contrast(colors[key], surface), 4.5, key)
        for key in ("control_border", "control_border_strong", "scroll_handle"):
            self.assertGreaterEqual(contrast(colors[key], surface), 3.0, key)

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

    def test_report_axis_labels_are_contextual_russian_and_never_iso(self) -> None:
        hours = [f"2026-07-20 {hour:02d}:00" for hour in range(24)]
        hour_labels = ReportsTab._axis_labels("hour", hours, "today")
        self.assertEqual([value for value in hour_labels if value], ["00", "04", "08", "12", "16", "20"])

        week = [f"2026-07-{day:02d}" for day in range(13, 20)]
        self.assertEqual(
            ReportsTab._axis_labels("day", week, "week"),
            ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"],
        )

        month = [f"2026-07-{day:02d}" for day in range(1, 32)]
        month_labels = ReportsTab._axis_labels("day", month, "month")
        self.assertTrue(all("-" not in value and "..." not in value for value in month_labels))
        self.assertEqual(month_labels[0], "1")
        self.assertEqual(month_labels[-1], "31")

        year = [f"2026-{month:02d}" for month in range(1, 13)]
        year_labels = ReportsTab._axis_labels("month", year, "year")
        self.assertEqual(year_labels[0], "янв.")
        self.assertEqual(year_labels[-1], "дек.")


if __name__ == "__main__":
    unittest.main()
