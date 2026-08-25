from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pc_stat_win.categories import ALL_CATEGORY_KEYS, CATEGORY_LABELS_RU
from pc_stat_win.db import AppStat, Database, PeriodStats
from pc_stat_win.exe_metadata import friendly_app_name
from pc_stat_win.formatting import format_duration_ms


_SPREADSHEET_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def spreadsheet_safe_text(value: object) -> str:
    """Keep user-controlled CSV text from becoming a spreadsheet formula."""
    text = str(value)
    candidate = text.lstrip(" \ufeff")
    if candidate.startswith(_SPREADSHEET_FORMULA_PREFIXES):
        return "'" + text
    return text


def export_apps_csv(
    db: Database, q_from: float, q_to: float, file_path: str, stats: PeriodStats | None = None
) -> None:
    """Write UTF-8 with BOM for Excel; semicolon separator."""
    stats = stats or db.period_stats(q_from, q_to)
    pc_ms = stats.pc_ms
    apps = stats.apps
    by_cat = stats.by_category
    target = Path(file_path)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=str(target.parent or Path(".")),
            prefix=f".{target.name}.",
            suffix=".tmp",
            newline="",
            encoding="utf-8-sig",
        ) as f:
            temp_name = f.name
            _write_apps_csv_rows(f, db, pc_ms, apps, by_cat)
        os.replace(temp_name, target)
    except Exception:
        if temp_name:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
        raise


def _write_apps_csv_rows(
    f: object,
    db: Database,
    pc_ms: float,
    apps: Sequence[AppStat],
    by_cat: dict[str, float],
) -> None:
    w = csv.writer(f, delimiter=";")
    w.writerow(
        ["friendly_name", "exe_path", "category", "active_ms", "active_human"]
    )
    for a in apps:
        cat = a.category or db.resolve_category(a.exe_path)
        w.writerow(
            [
                spreadsheet_safe_text(friendly_app_name(a.exe_path)),
                spreadsheet_safe_text(a.exe_path),
                spreadsheet_safe_text(CATEGORY_LABELS_RU.get(cat, cat)),
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
    for key in ALL_CATEGORY_KEYS:
        ms = by_cat.get(key, 0.0)
        w.writerow([key, int(round(ms)), format_duration_ms(ms)])
