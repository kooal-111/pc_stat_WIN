from __future__ import annotations


def format_duration_ms(ms: float) -> str:
    if ms < 1000:
        return f"{int(ms)} мс"
    sec = int(round(ms / 1000.0))
    if sec < 60:
        return f"{sec} с"
    m, s = divmod(sec, 60)
    if m < 60:
        return f"{m} м {s} с"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} ч {m} м"
    d, h = divmod(h, 24)
    return f"{d} д {h} ч"


def format_duration_seconds(sec: float) -> str:
    return format_duration_ms(sec * 1000.0)
