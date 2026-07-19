from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_stat_win.collector import UsageCollector
from pc_stat_win.db import Database
from pc_stat_win.foreground import ForegroundInfo


class BenchmarkClock:
    def __init__(self) -> None:
        self.wall = 1_000_000.0
        self.monotonic = 0.0

    def advance(self, seconds: float) -> None:
        self.wall += seconds
        self.monotonic += seconds


def run_benchmark(session_seconds: int, tick_seconds: int) -> dict[str, float | int | bool]:
    if session_seconds <= 0 or tick_seconds <= 0:
        raise ValueError("session and tick durations must be positive")
    ticks = session_seconds // tick_seconds
    if ticks == 0:
        raise ValueError("session must contain at least one tick")

    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "switches.sqlite")
        clock = BenchmarkClock()
        active = {"value": None}

        def current_foreground() -> ForegroundInfo | None:
            return active["value"]

        collector = UsageCollector(
            db,
            poll_interval_ms=tick_seconds * 1_000,
            wall_clock=lambda: clock.wall,
            monotonic_clock=lambda: clock.monotonic,
            foreground_provider=current_foreground,
            idle_provider=lambda: 0.0,
            boot_time_provider=lambda: clock.wall - 500.0,
            retry_sleep=lambda _seconds: None,
        )
        transactions = 0

        def trace(sql: str) -> None:
            nonlocal transactions
            if sql.strip().upper().startswith("BEGIN IMMEDIATE"):
                transactions += 1

        db._conn.set_trace_callback(trace)
        started = time.perf_counter()
        for index in range(ticks):
            name = f"switch-{index % 8}.exe"
            active["value"] = ForegroundInfo(
                hwnd=index + 1,
                pid=index + 10,
                exe_path=rf"C:\Synthetic\{name}",
                exe_name=name,
                window_title=f"Window {index}",
            )
            clock.advance(float(tick_seconds))
            collector._on_tick()
        stopped_cleanly = collector.stop()
        elapsed = time.perf_counter() - started
        db._conn.set_trace_callback(None)

        q_from = clock.wall - ticks * tick_seconds - 1.0
        q_to = clock.wall + 1.0
        pc_ms = db.total_pc_ms(q_from, q_to)
        app_ms = sum(row.active_ms for row in db.totals_by_app(q_from, q_to))
        app_rows = int(
            db._conn.execute(
                "SELECT COUNT(*) FROM intervals WHERE kind = 'app'"
            ).fetchone()[0]
        )
        db.close()

    expected_ms = ticks * tick_seconds * 1_000
    transaction_budget = math.ceil(ticks * tick_seconds / 30.0) + 3
    passed = (
        stopped_cleanly
        and transactions <= transaction_budget
        and pc_ms == expected_ms
        and app_ms == expected_ms
        and app_rows == ticks
    )
    return {
        "session_seconds": ticks * tick_seconds,
        "ticks_and_switches": ticks,
        "transactions": transactions,
        "transaction_budget": transaction_budget,
        "transactions_per_hour": round(
            transactions * 3_600 / (ticks * tick_seconds), 2
        ),
        "app_rows": app_rows,
        "pc_ms": int(pc_ms),
        "app_ms": int(app_ms),
        "elapsed_seconds": round(elapsed, 4),
        "passed": passed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark collector transaction cost during rapid app switches."
    )
    parser.add_argument("--session-seconds", type=int, default=3_600)
    parser.add_argument("--tick-seconds", type=int, default=2)
    args = parser.parse_args()
    result = run_benchmark(args.session_seconds, args.tick_seconds)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
