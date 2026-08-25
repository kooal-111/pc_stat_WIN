from __future__ import annotations

import logging
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pc_stat_win.config import default_db_path


LOG_FILENAME = "pc_stat.log"
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def default_log_path() -> Path:
    return default_db_path().parent / "logs" / LOG_FILENAME


def _fallback_log_path() -> Path:
    return Path(tempfile.gettempdir()) / "pc_stat_win" / "logs" / LOG_FILENAME


def _file_handler(path: Path, level: int) -> RotatingFileHandler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    return handler


def configure_logging(
    log_path: Path | None = None,
    level: int = logging.INFO,
) -> Path:
    """Configure logging without making startup depend on the profile directory."""
    primary_path = (log_path or default_log_path()).resolve()
    fallback_path = _fallback_log_path().resolve()
    candidates = [primary_path]
    if fallback_path != primary_path:
        candidates.append(fallback_path)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    last_error: OSError | None = None

    for path in candidates:
        for handler in root_logger.handlers:
            if (
                isinstance(handler, RotatingFileHandler)
                and Path(handler.baseFilename) == path
            ):
                handler.setLevel(level)
                return path
        try:
            handler = _file_handler(path, level)
        except OSError as exc:
            last_error = exc
            continue

        root_logger.addHandler(handler)
        if last_error is not None:
            root_logger.warning(
                "Primary log file is unavailable: %s; using %s",
                last_error,
                path,
            )
        logging.captureWarnings(True)
        return path

    if not any(
        isinstance(handler, logging.NullHandler) for handler in root_logger.handlers
    ):
        root_logger.addHandler(logging.NullHandler())
    logging.captureWarnings(True)
    return fallback_path
