"""Measure the no-window collector baseline against a temporary SQLite DB."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from pc_stat_win.collector import UsageCollector
from pc_stat_win.db import Database


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=60.0)
    args = parser.parse_args()
    seconds = max(2.0, args.seconds)

    app = QApplication([])
    process = psutil.Process()
    with tempfile.TemporaryDirectory(prefix="pc_stat_background_") as tmp:
        db = Database(Path(tmp) / "data.sqlite")
        collector = UsageCollector(db)
        changes_before = db._conn.total_changes
        cpu_before = sum(process.cpu_times()[:2])
        started = time.perf_counter()
        collector.start()
        QTimer.singleShot(int(seconds * 1000), app.quit)
        app.exec()
        collector.stop()
        elapsed = time.perf_counter() - started
        cpu_seconds = sum(process.cpu_times()[:2]) - cpu_before
        print(f"elapsed_s={elapsed:.2f}")
        print(f"avg_cpu_one_core_pct={100.0 * cpu_seconds / elapsed:.3f}")
        print(f"rss_mb={process.memory_info().rss / 1024 / 1024:.1f}")
        print(f"db_changes={db._conn.total_changes - changes_before}")
        print(f"main_window_loaded={'pc_stat_win.ui.main_window' in sys.modules}")
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
