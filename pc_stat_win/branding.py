from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)


def _assets_icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "app_icon.png"


def _render_icon_pixmap(size: int) -> QPixmap:
    """Raster icon: gradient tile + bar chart + clock hint — no external assets required."""
    s = max(16, size)
    pm = QPixmap(s, s)
    pm.fill(QColor(0, 0, 0, 0))

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pad = max(2, s // 12)
    r = s // 10

    grad = QLinearGradient(0, 0, float(s), float(s))
    grad.setColorAt(0.0, QColor("#89b4fa"))
    grad.setColorAt(0.55, QColor("#cba6f7"))
    grad.setColorAt(1.0, QColor("#94e2d5"))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor("#11111b"), max(1, s // 64)))
    p.drawRoundedRect(pad, pad, s - 2 * pad, s - 2 * pad, r, r)

    # Bars
    bx0 = pad + s // 6
    bw = (s - 2 * pad - s // 5) // 5
    gap = max(1, s // 48)
    heights = (0.35, 0.55, 0.85, 0.45, 0.7)
    base_y = s - pad - s // 8
    bar_w = bw - gap
    for i, h in enumerate(heights):
        x = bx0 + i * bw
        bh = int((s // 2.2) * h)
        p.setBrush(QColor("#1e1e2e"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(x, base_y - bh, bar_w, bh, 2, 2)

    # Clock arc
    cx, cy = s // 2, pad + s // 4
    rad = s // 7
    p.setPen(QPen(QColor("#1e1e2e"), max(2, s // 48)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(cx - rad, cy - rad, 2 * rad, 2 * rad, 30 * 16, 220 * 16)
    p.end()
    return pm


def app_icon() -> QIcon:
    """Application icon for window, taskbar, and tray."""
    path = _assets_icon_path()
    if path.is_file():
        ico = QIcon(str(path))
        if not ico.isNull():
            return ico

    ico = QIcon()
    for sz in (256, 128, 64, 48, 32, 24, 16):
        pm = _render_icon_pixmap(sz)
        ico.addPixmap(pm, QIcon.Mode.Normal, QIcon.State.Off)
    return ico
