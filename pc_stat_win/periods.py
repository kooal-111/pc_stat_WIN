from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Literal

Period = Literal["today", "week", "month", "year", "all"]

_MONTHS_RU = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_MONTHS_NOMINATIVE_RU = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
_WEEKDAYS_RU = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)


def _shift_month_start(value: datetime, months: int) -> datetime:
    absolute_month = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute_month, 12)
    return value.replace(
        year=year,
        month=month_index + 1,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def _local_datetime(timestamp: float) -> datetime:
    local_tz = datetime.now().astimezone().tzinfo
    return datetime.fromtimestamp(timestamp, tz=local_tz)


def period_range(
    period: Period,
    *,
    all_start: float | None = None,
    offset: int = 0,
    now: float | None = None,
) -> tuple[float, float]:
    """Calendar-aware ranges in local timezone (week from Monday 00:00; year from Jan 1).

    For ``all``, pass ``all_start`` from the database (first interval), or bounds fall back to
    epoch 0 when unknown (empty DB).
    """
    now_ts = time.time() if now is None else float(now)
    if period == "all":
        start = all_start if all_start is not None else 0.0
        return start, now_ts

    local = _local_datetime(now_ts)
    offset = min(0, int(offset))

    if period == "today":
        current_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        start = current_start + timedelta(days=offset)
        end = local if offset == 0 else start + timedelta(days=1)
        return start.timestamp(), end.timestamp()

    if period == "week":
        current_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        current_start -= timedelta(days=local.weekday())
        start = current_start + timedelta(weeks=offset)
        end = local if offset == 0 else start + timedelta(days=7)
        return start.timestamp(), end.timestamp()

    if period == "month":
        start = _shift_month_start(local, offset)
        end = local if offset == 0 else _shift_month_start(start, 1)
        return start.timestamp(), end.timestamp()

    if period == "year":
        start = local.replace(
            year=local.year + offset,
            month=1,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        end = local if offset == 0 else start.replace(year=start.year + 1)
        return start.timestamp(), end.timestamp()

    return 0.0, now_ts


def previous_period_range(period: Period, q_from: float, q_to: float) -> tuple[float, float] | None:
    if period == "all" or q_to <= q_from:
        return None
    span = q_to - q_from
    if period == "today":
        return q_from - 86400.0, q_to - 86400.0
    if period == "week":
        return q_from - 7 * 86400.0, q_to - 7 * 86400.0
    if period == "month":
        local_start = _local_datetime(q_from)
        prev_end = local_start
        prev_start = (local_start.replace(day=1) - timedelta(days=1)).replace(day=1)
        return prev_start.timestamp(), min(prev_end.timestamp(), prev_start.timestamp() + span)
    if period == "year":
        local_start = _local_datetime(q_from)
        prev_start = local_start.replace(year=local_start.year - 1)
        return prev_start.timestamp(), min(q_from, prev_start.timestamp() + span)
    return q_from - span, q_from


def period_title(
    period: Period,
    q_from: float,
    q_to: float,
    *,
    now: float | None = None,
) -> str:
    """Human-readable Russian title for a selected calendar range."""
    if period == "all":
        return "За всё время"

    start = _local_datetime(q_from)
    end = _local_datetime(max(q_from, q_to - 0.001))
    now_local = _local_datetime(time.time() if now is None else now)

    if period == "today":
        date = start.date()
        if date == now_local.date():
            prefix = "Сегодня"
        elif date == (now_local - timedelta(days=1)).date():
            prefix = "Вчера"
        else:
            prefix = _WEEKDAYS_RU[start.weekday()]
        return f"{prefix}, {start.day} {_MONTHS_RU[start.month - 1]}"

    if period == "week":
        end = start + timedelta(days=6)
        if start.year == end.year and start.month == end.month:
            suffix = f"{_MONTHS_RU[end.month - 1]} {end.year}"
            return f"{start.day}–{end.day} {suffix}"
        if start.year == end.year:
            return (
                f"{start.day} {_MONTHS_RU[start.month - 1]} – "
                f"{end.day} {_MONTHS_RU[end.month - 1]} {end.year}"
            )
        return (
            f"{start.day} {_MONTHS_RU[start.month - 1]} {start.year} – "
            f"{end.day} {_MONTHS_RU[end.month - 1]} {end.year}"
        )

    if period == "month":
        return f"{_MONTHS_NOMINATIVE_RU[start.month - 1]} {start.year}"

    return f"{start.year} год"
