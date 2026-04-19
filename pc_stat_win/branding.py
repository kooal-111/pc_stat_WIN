from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QCoreApplication
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def _resolve_assets_png() -> Path | None:
    d = _assets_dir()
    for name in ("app.png", "app_icon.png"):
        p = d / name
        if p.is_file():
            return p
    return None


def render_app_icon_pixmap(size: int) -> QPixmap:
    """Raster icon: soft tile, bar chart, clock — used at runtime and for .ico build."""
    s = max(16, size)
    pm = QPixmap(s, s)
    pm.fill(QColor(0, 0, 0, 0))

    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    pad = max(3, s // 10)
    r = max(6, s // 8)

    # Main tile gradient (soft blue–lavender–mint)
    grad = QLinearGradient(0, 0, float(s), float(s))
    grad.setColorAt(0.0, QColor("#89b4fa"))
    grad.setColorAt(0.42, QColor("#b4befe"))
    grad.setColorAt(1.0, QColor("#a6e3a1"))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor(30, 30, 46, 200), max(1, s // 96)))
    p.drawRoundedRect(pad, pad, s - 2 * pad, s - 2 * pad, r, r)

    # Inner highlight (top edge)
    hi = QLinearGradient(0, float(pad), 0, float(s // 2))
    hi.setColorAt(0.0, QColor(255, 255, 255, 70))
    hi.setColorAt(1.0, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(hi))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(pad + 1, pad + 1, s - 2 * pad - 2, (s - 2 * pad) // 2, r - 1, r - 1)

    # Bars
    bx0 = pad + s // 7
    bw = (s - 2 * pad - s // 6) // 5
    gap = max(1, s // 42)
    heights = (0.38, 0.58, 0.88, 0.48, 0.72)
    base_y = s - pad - s // 7
    bar_w = max(2, bw - gap)
    for i, h in enumerate(heights):
        x = bx0 + i * bw
        bh = int((s // 2.0) * h)
        bx, by, bw_, bh_ = x, base_y - bh, bar_w, bh
        # bar body (slightly cool gray)
        p.setBrush(QColor("#45475a"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(bx, by, bw_, bh_, 3, 3)
        # top cap highlight (frosted)
        cap_h = max(2, bh_ // 5)
        cap_grad = QLinearGradient(0, float(by), 0, float(by + cap_h))
        cap_grad.setColorAt(0.0, QColor(203, 213, 245, 110))
        cap_grad.setColorAt(1.0, QColor(69, 71, 90, 0))
        p.setBrush(QBrush(cap_grad))
        p.drawRoundedRect(bx, by, bw_, min(cap_h, bh_), 2, 2)

    # Clock arc
    cx, cy = s // 2, pad + s // 4
    rad = max(6, s // 6)
    p.setPen(QPen(QColor(30, 30, 46, 220), max(2, s // 42)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawArc(cx - rad, cy - rad, 2 * rad, 2 * rad, 35 * 16, 215 * 16)
    p.end()
    return pm


def write_packaged_icon_assets() -> tuple[Path, Path]:
    """Write pc_stat_win/assets/app.png + app.ico for PyInstaller (run from build)."""
    if QCoreApplication.instance() is None:
        from PySide6.QtGui import QGuiApplication

        _ = QGuiApplication(sys.argv)
    d = _assets_dir()
    d.mkdir(parents=True, exist_ok=True)
    png_path = d / "app.png"
    ico_path = d / "app.ico"
    pm = render_app_icon_pixmap(256)
    if not pm.save(str(png_path), "PNG"):
        raise OSError(f"Failed to write {png_path}")
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    if not img.save(str(ico_path), "ICO"):
        raise OSError(
            f"Failed to write {ico_path} (ICO). Ensure Qt imageformats include ico."
        )
    return png_path, ico_path


def app_icon() -> QIcon:
    """Application icon for window, taskbar, and tray."""
    path = _resolve_assets_png()
    if path is not None:
        ico = QIcon(str(path))
        if not ico.isNull():
            return ico

    ico = QIcon()
    for sz in (256, 128, 64, 48, 32, 24, 16):
        pm = render_app_icon_pixmap(sz)
        ico.addPixmap(pm, QIcon.Mode.Normal, QIcon.State.Off)
    return ico
