from __future__ import annotations

import csv

from pc_stat_win.categories import CATEGORY_LABELS_RU, NEUTRAL, PRODUCTIVE, UNPRODUCTIVE
from pc_stat_win.db import Database
from pc_stat_win.exe_metadata import friendly_app_name
from pc_stat_win.formatting import format_duration_ms


def export_apps_csv(db: Database, q_from: float, q_to: float, file_path: str) -> None:
    """Write UTF-8 with BOM for Excel; semicolon separator."""
    pc_ms = db.total_pc_ms(q_from, q_to)
    apps = db.totals_by_app(q_from, q_to)
    by_cat = db.totals_by_category(q_from, q_to)
    with open(file_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(
            ["friendly_name", "exe_path", "category", "active_ms", "active_human"]
        )
        for a in apps:
            cat = db.resolve_category(a.exe_path)
            w.writerow(
                [
                    friendly_app_name(a.exe_path),
                    a.exe_path,
                    CATEGORY_LABELS_RU.get(cat, cat),
                    int(round(a.active_ms)),
                    format_duration_ms(a.active_ms),
                ]
            )
        w.writerow([])
        w.writerow(["# Итог активного времени ПК"])
        w.writerow(
            [
                "total_pc_active_ms",
                int(round(pc_ms)),
                format_duration_ms(pc_ms),
            ]
        )
        w.writerow([])
        w.writerow(["# Суммы по категориям (по приложениям в фокусе)"])
        w.writerow(["category_key", "active_ms", "active_human"])
        for key in (PRODUCTIVE, UNPRODUCTIVE, NEUTRAL):
            ms = by_cat.get(key, 0.0)
            w.writerow([key, int(round(ms)), format_duration_ms(ms)])
