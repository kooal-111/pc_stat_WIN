from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QCoreApplication, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap


ICON_PNG_SIZE = 512
ICON_ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def _resolve_assets_png() -> Path | None:
    assets = _assets_dir()
    for name in ("app.png", "app_icon.png"):
        path = assets / name
        if path.is_file():
            return path
    return None


def render_app_icon_pixmap(size: int) -> QPixmap:
    """Render the packaged icon at an exact device-independent size."""
    target = max(16, int(size))
    source_path = _resolve_assets_png()
    if source_path is not None:
        source = QPixmap(str(source_path))
        if not source.isNull():
            return source.scaled(
                target,
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

    fallback = QPixmap(target, target)
    fallback.fill(QColor("#2563EB"))
    return fallback


def _square_image(source: QImage, size: int) -> QImage:
    """Center-crop a source and downsample it to a square icon image."""
    side = min(source.width(), source.height())
    x = max(0, (source.width() - side) // 2)
    y = max(0, (source.height() - side) // 2)
    square = source.copy(x, y, side, side)
    result = square.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    ).convertToFormat(QImage.Format.Format_ARGB32)
    inset = max(1.0, size * 0.008)
    radius = size * 0.14
    mask = QImage(size, size, QImage.Format.Format_ARGB32)
    mask.fill(Qt.GlobalColor.transparent)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(Qt.GlobalColor.white)
    painter.drawRoundedRect(
        QRectF(inset, inset, size - 2 * inset, size - 2 * inset),
        radius,
        radius,
    )
    painter.end()
    painter = QPainter(result)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    painter.drawImage(0, 0, mask)
    painter.end()
    return result


def _png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
        raise OSError("Unable to open the icon image buffer")
    try:
        if not image.save(buffer, "PNG"):
            raise OSError("Unable to encode an icon layer as PNG")
    finally:
        buffer.close()
    return bytes(data)


def _write_multi_size_ico(source: QImage, path: Path) -> None:
    payloads = [_png_bytes(_square_image(source, size)) for size in ICON_ICO_SIZES]
    offset = 6 + 16 * len(payloads)
    directory = bytearray(struct.pack("<HHH", 0, 1, len(payloads)))
    for size, payload in zip(ICON_ICO_SIZES, payloads, strict=True):
        encoded_size = 0 if size == 256 else size
        directory.extend(
            struct.pack(
                "<BBBBHHII",
                encoded_size,
                encoded_size,
                0,
                0,
                1,
                32,
                len(payload),
                offset,
            )
        )
        offset += len(payload)
    path.write_bytes(bytes(directory) + b"".join(payloads))


def write_packaged_icon_assets(source_path: str | Path | None = None) -> tuple[Path, Path]:
    """Create the runtime PNG and a true multi-resolution Windows ICO."""
    if QCoreApplication.instance() is None:
        from PySide6.QtGui import QGuiApplication

        _ = QGuiApplication(sys.argv)

    assets = _assets_dir()
    assets.mkdir(parents=True, exist_ok=True)
    png_path = assets / "app.png"
    ico_path = assets / "app.ico"
    source = Path(source_path) if source_path is not None else png_path
    image = QImage(str(source))
    if image.isNull():
        raise OSError(f"Unable to load icon source: {source}")

    master = _square_image(image, ICON_PNG_SIZE)
    if not master.save(str(png_path), "PNG"):
        raise OSError(f"Unable to write {png_path}")
    _write_multi_size_ico(master, ico_path)
    return png_path, ico_path


def app_icon() -> QIcon:
    """Application icon for the window, taskbar, and notification area."""
    icon = QIcon()
    if _resolve_assets_png() is not None:
        for size in ICON_ICO_SIZES:
            pixmap = render_app_icon_pixmap(size)
            if not pixmap.isNull():
                icon.addPixmap(pixmap, QIcon.Mode.Normal, QIcon.State.Off)
    return icon
