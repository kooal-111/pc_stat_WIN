from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pc_stat_win.config import default_db_path


LOG_FILENAME = "pc_stat.log"
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def default_log_path() -> Path:
    return default_db_path().parent / "logs" / LOG_FILENAME


def configure_logging(
    log_path: Path | None = None,
    level: int = logging.INFO,
) -> Path:
    """Configure the root logger with one 1 MiB rotating file handler."""
    path = (log_path or default_log_path()).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        if (
            isinstance(handler, RotatingFileHandler)
            and Path(handler.baseFilename) == path
        ):
            handler.setLevel(level)
            return path

    handler = RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(handler)
    logging.captureWarnings(True)
    return path
