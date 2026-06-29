from __future__ import annotations

import random
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pc_stat_win.db import Database


def main() -> int:
    rows = 100_000
    now = time.time()
    start = now - rows * 60.0
    exes = [
        (r"C:\Program Files\Google\Chrome\Application\chrome.exe", "chrome.exe"),
        (r"C:\Users\User\AppData\Local\Programs\Microsoft VS Code\Code.exe", "code.exe"),
        (r"C:\Windows\explorer.exe", "explorer.exe"),
        (r"C:\Program Files\Telegram Desktop\Telegram.exe", "telegram.exe"),
    ]
    with tempfile.TemporaryDirectory(prefix="pc_stat_perf_") as tmp:
        db = Database(Path(tmp) / "data.sqlite")
        t0 = time.perf_counter()
        with db.transaction() as conn:
            for i in range(rows):
                ts0 = start + i * 60.0
                ts1 = ts0 + random.randint(5, 55)
                exe_path, exe_name = exes[i % len(exes)]
                conn.execute(
                    """
                    INSERT INTO intervals
                      (kind, exe_path, exe_name, window_title, start_ts, end_ts, duration_ms)
                    VALUES ('app', ?, ?, NULL, ?, ?, ?)
                    """,
                    (exe_path, exe_name, ts0, ts1, int((ts1 - ts0) * 1000)),
                )
                conn.execute(
                    """
                    INSERT INTO intervals
                      (kind, exe_path, exe_name, window_title, start_ts, end_ts, duration_ms)
                    VALUES ('pc_active', NULL, NULL, NULL, ?, ?, ?)
                    """,
                    (ts0, ts1, int((ts1 - ts0) * 1000)),
                )
        insert_s = time.perf_counter() - t0

        q_from = now - 7 * 86400
        q_to = now
        t1 = time.perf_counter()
        stats = db.period_stats(q_from, q_to)
        query_s = time.perf_counter() - t1
        plan = db._conn.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT start_ts, end_ts, duration_ms
            FROM intervals
            WHERE kind = 'pc_active' AND start_ts < ? AND end_ts > ?
            """,
            (q_to, q_from),
        ).fetchall()
        print(f"insert_s={insert_s:.2f}")
        print(f"period_stats_s={query_s:.3f}")
        print(f"pc_ms={stats.pc_ms:.0f} apps={len(stats.apps)} chart={len(stats.chart_series)}")
        print("query_plan=" + " | ".join(str(tuple(r)) for r in plan))
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
