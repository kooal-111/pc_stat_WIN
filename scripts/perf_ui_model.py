"""Measure sorting/filtering 10k application rows without building widgets."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from pc_stat_win.db import AppStat
from pc_stat_win.ui.app_table import AppFilterProxyModel, AppTableModel


def main() -> int:
    QApplication.instance() or QApplication([])
    rows = [
        AppStat(
            exe_name=f"application-{index}.exe",
            exe_path=rf"C:\Apps\Group-{index % 20}\application-{index}.exe",
            active_ms=float(index * 1000),
            category="browser" if index % 2 else "devtools",
        )
        for index in range(10_000)
    ]
    model = AppTableModel(rows, total_ms=sum(row.active_ms for row in rows))
    proxy = AppFilterProxyModel()
    proxy.setSourceModel(model)

    started = time.perf_counter()
    for query in ("group-7", "application-999", "group-12 application") * 10:
        proxy.set_filter_text(query)
        proxy.rowCount()
    elapsed_ms = 1000.0 * (time.perf_counter() - started) / 30.0
    print(f"rows={len(rows)} average_filter_ms={elapsed_ms:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
