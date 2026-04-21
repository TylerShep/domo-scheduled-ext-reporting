"""Tiny CLI entry point equivalent to ``domo-report --download-jar``.

Exists so Docker builds can do ``python -m app.engines.jar_download_cli``
without pulling in the rest of :mod:`main`.
"""

from __future__ import annotations

import sys

from app.engines.jar_downloader import (
    JarDownloadError,
    default_install_path,
    describe_version,
    download_jar,
)
from app.utils.logger import configure_logging, get_logger


def main() -> int:
    configure_logging()
    logger = get_logger(__name__)
    logger.info("Target install path: %s", default_install_path())
    logger.info("Pinned JAR version: %s", describe_version())
    try:
        path = download_jar()
    except JarDownloadError as exc:
        logger.error("JAR download failed: %s", exc)
        return 1
    logger.info("Installed JAR -> %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
