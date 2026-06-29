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


def previous_period_range(period: Period, q_from: float, q_to: float) -> tuple[float, float] | None:
    if period == "all" or q_to <= q_from:
        return None
    span = q_to - q_from
    if period == "today":
        return q_from - 86400.0, q_to - 86400.0
    if period == "week":
        return q_from - 7 * 86400.0, q_to - 7 * 86400.0
    if period == "month":
        local_start = datetime.fromtimestamp(q_from).astimezone()
        prev_end = local_start
        prev_start = (local_start.replace(day=1) - timedelta(days=1)).replace(day=1)
        return prev_start.timestamp(), min(prev_end.timestamp(), prev_start.timestamp() + span)
    if period == "year":
        local_start = datetime.fromtimestamp(q_from).astimezone()
        prev_start = local_start.replace(year=local_start.year - 1)
        return prev_start.timestamp(), min(q_from, prev_start.timestamp() + span)
    return q_from - span, q_from
