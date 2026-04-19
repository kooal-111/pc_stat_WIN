from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Literal

Period = Literal["today", "week", "month", "year", "all"]


def period_range(
    period: Period, *, all_start: float | None = None
) -> tuple[float, float]:
    """Calendar-aware ranges in local timezone (week from Monday 00:00; year from Jan 1).

    For ``all``, pass ``all_start`` from the database (first interval), or bounds fall back to
    epoch 0 when unknown (empty DB).
    """
    now = time.time()
    if period == "all":
        start = all_start if all_start is not None else 0.0
        return start, now

    local = datetime.now().astimezone()
    tz = local.tzinfo

    if period == "today":
        start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), now

    if period == "week":
        # Monday 00:00 of current week (Monday = 0 in weekday() for ISO: Monday is 0 in Python weekday())
        wd = local.weekday()  # Mon=0 .. Sun=6
        start_day = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=wd)
        return start_day.timestamp(), now

    if period == "month":
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), now

    if period == "year":
        start = local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp(), now

    return 0.0, now
