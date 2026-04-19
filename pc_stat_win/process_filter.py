from __future__ import annotations

import os

from pc_stat_win.config import SYSTEM32_SILENT_EXES


def _in_system32(path: str) -> bool:
    p = path.replace("/", "\\").lower()
    return "\\windows\\system32\\" in p or p.endswith("\\windows\\system32")


def should_track_foreground(exe_path: str, exe_name: str, extra_excluded: frozenset[str]) -> bool:
    """
    Skip typical background / shell noise when it appears as foreground
    (rare) or path-based heuristics for non-user apps.
    """
    name = exe_name.lower()
    if name in extra_excluded:
        return False
    if name in SYSTEM32_SILENT_EXES and _in_system32(exe_path):
        return False
    base = os.path.basename(exe_path).lower()
    if base == "explorer.exe" and _in_system32(exe_path):
        # Desktop / shell — still user-visible; track
        return True
    return True
