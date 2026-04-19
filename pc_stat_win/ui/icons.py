from __future__ import annotations

import os
from functools import lru_cache

from PySide6.QtCore import QFileInfo, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider, QApplication

_ICON_PX = 28
_provider = QFileIconProvider()


def _norm_path(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(path))
    except OSError:
        return path


@lru_cache(maxsize=256)
def app_icon_for_exe(exe_path: str) -> QIcon:
    """Shell-style icon for an executable, fixed size."""
    if QApplication.instance() is None:
        return QIcon()

    p = _norm_path(exe_path)
    if not p or not os.path.isfile(p):
        try:
            return _provider.icon(QFileIconProvider.IconType.File)
        except Exception:
            return QIcon()

    try:
        ico = _provider.icon(QFileInfo(p))
    except Exception:
        return QIcon()
    pm = ico.pixmap(_ICON_PX, _ICON_PX)
    if pm.isNull():
        return ico
    scaled = pm.scaled(
        _ICON_PX,
        _ICON_PX,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    return QIcon(scaled)
