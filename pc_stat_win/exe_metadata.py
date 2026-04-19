from __future__ import annotations

import os
import struct
from functools import lru_cache
from pathlib import Path

import win32api


def _norm_path(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(path))
    except OSError:
        return path


def _fallback_name(path: str) -> str:
    stem = Path(path).stem
    if not stem:
        return path
    return stem.replace("_", " ").strip() or stem


def _translation_pairs(trans: object) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    if trans is None:
        return pairs
    if isinstance(trans, bytes):
        for off in range(0, len(trans), 4):
            if off + 4 <= len(trans):
                lang, cp = struct.unpack_from("<HH", trans, off)
                pairs.append((lang, cp))
        return pairs
    if isinstance(trans, (list, tuple)):
        if (
            len(trans) == 2
            and isinstance(trans[0], int)
            and isinstance(trans[1], int)
        ):
            return [(int(trans[0]), int(trans[1]))]
        for item in trans:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                pairs.append((int(item[0]), int(item[1])))
        if not pairs and trans and isinstance(trans[0], int):
            for i in range(0, len(trans) - 1, 2):
                pairs.append((int(trans[i]), int(trans[i + 1])))
    return pairs


def _version_string_field(path: str, field: str) -> str | None:
    try:
        trans = win32api.GetFileVersionInfo(path, "\\VarFileInfo\\Translation")
    except win32api.error:
        trans = None

    pairs = _translation_pairs(trans)
    if not pairs:
        pairs = [(0x0409, 0x04B0), (0x0419, 0x04B0)]

    for lang, cp in pairs:
        subblock = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{field}"
        try:
            val = win32api.GetFileVersionInfo(path, subblock)
            if val and str(val).strip():
                return str(val).strip()
        except win32api.error:
            continue

    for block in ("040904B0", "040904E4", "041904E4"):
        subblock = f"\\StringFileInfo\\{block}\\{field}"
        try:
            val = win32api.GetFileVersionInfo(path, subblock)
            if val and str(val).strip():
                return str(val).strip()
        except win32api.error:
            continue
    return None


@lru_cache(maxsize=256)
def friendly_app_name(exe_path: str) -> str:
    """Display name from PE version resource, else basename."""
    p = _norm_path(exe_path)
    if not p or not os.path.isfile(p):
        return _fallback_name(exe_path)

    for field in ("FileDescription", "ProductName"):
        s = _version_string_field(p, field)
        if s:
            return s
    return _fallback_name(p)
