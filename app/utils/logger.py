"""Project-wide logging configuration.

Call :func:`configure_logging` once at startup (``main.py`` does this) and
then use ``logging.getLogger(__name__)`` everywhere else.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(level: str | None = None, log_file: str | None = None) -> None:
    """Install console (and optional rotating file) handlers on the root logger.

    Idempotent -- safe to call multiple times.

    Args:
        level: Log level name (``DEBUG``/``INFO``/...). Defaults to ``LOG_LEVEL``
            env var or ``INFO``.
        log_file: Path to a log file. Defaults to ``LOG_FILE`` env var. If
            unset, only the console handler is attached.
    """

    global _configured
    if _configured:
        return

    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, level_name, logging.INFO)

    formatter = logging.Formatter(_LOG_FORMAT, _DATE_FORMAT)
    root = logging.getLogger()
    root.setLevel(log_level)

    for handler in list(root.handlers):
        root.removeHandler(handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    file_path = log_file or os.getenv("LOG_FILE")
    if file_path:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    # Quiet down noisy third-party loggers.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("msal").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper so callers don't have to import :mod:`logging`."""

    return logging.getLogger(name)
