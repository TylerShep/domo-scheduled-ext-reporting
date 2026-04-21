"""Download + verify the Domo CLI JAR.

The bundled ``domoUtil.jar`` is ~55 MiB -- too big to live in a Python
package / git repo comfortably.  We ship a tiny metadata file
(:data:`_VERSION_FILE`) and fetch the binary on demand.

Security model
--------------
1. The download URL is pinned per version in
   ``app/engines/JAR_VERSION.json``.
2. After download, the SHA-256 is verified against the pinned hash. If
   it doesn't match, the downloaded bytes are deleted and a
   :class:`JarDownloadError` is raised.
3. Users may override the URL via ``DOMO_JAR_URL`` but cannot override
   the expected hash from the environment -- that would defeat the
   integrity check.

CLI entry point: ``domo-report --download-jar``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)


_VERSION_FILE = Path(__file__).resolve().parent / "JAR_VERSION.json"
_DEFAULT_INSTALL_DIR = Path(__file__).resolve().parent.parent / "utils"
_DEFAULT_INSTALL_PATH = _DEFAULT_INSTALL_DIR / "domoUtil.jar"


class JarDownloadError(RuntimeError):
    """Raised when the download, hash check, or install fails."""


@dataclass(frozen=True)
class JarVersion:
    """Pinned JAR metadata loaded from ``JAR_VERSION.json``."""

    version: str
    filename: str
    url: str
    sha256: str
    notes: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> JarVersion:
        src = path or _VERSION_FILE
        try:
            with src.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError as exc:
            raise JarDownloadError(f"JAR version file missing: {src}") from exc
        except json.JSONDecodeError as exc:
            raise JarDownloadError(f"JAR version file is not valid JSON: {exc}") from exc

        missing = {"version", "filename", "url", "sha256"} - set(data)
        if missing:
            raise JarDownloadError(f"JAR version file missing required keys: {sorted(missing)}")
        return cls(
            version=str(data["version"]),
            filename=str(data["filename"]),
            url=str(data["url"]),
            sha256=str(data["sha256"]).lower(),
            notes=str(data.get("notes", "")),
        )


# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------


def sha256_file(path: Path | str, *, chunk: int = 1024 * 1024) -> str:
    """Compute the SHA-256 of a file path, returned lower-case hex."""

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify_jar(path: Path | str, expected_sha256: str) -> bool:
    """Return True iff ``path`` matches ``expected_sha256`` byte for byte."""

    actual = sha256_file(path).lower()
    return actual == expected_sha256.lower()


def jar_is_installed(path: Path | str | None = None) -> bool:
    """Return True if the JAR exists at ``path`` (or the default install path)."""

    p = Path(path) if path else _DEFAULT_INSTALL_PATH
    return p.is_file() and p.stat().st_size > 0


# ---------------------------------------------------------------------------
# Download + install
# ---------------------------------------------------------------------------


def download_jar(
    *,
    install_path: Path | str | None = None,
    version: JarVersion | None = None,
    url_override: str | None = None,
    force: bool = False,
    fetch: callable | None = None,
) -> Path:
    """Download + verify the Domo CLI JAR.

    Args:
        install_path: Where to write the file on success. Defaults to
            ``app/utils/domoUtil.jar``.
        version: Pre-loaded :class:`JarVersion`. Loads from disk if None.
        url_override: Override the pinned URL (e.g. for a corporate
            mirror).  The pinned SHA-256 is still enforced.
        force: Re-download even if a file is already installed and
            passes verification.
        fetch: Testing hook -- a callable ``(url, dest_path) -> None``
            that writes bytes to ``dest_path``.  Defaults to urllib.

    Returns:
        The path the JAR was written to.

    Raises:
        JarDownloadError: Network failure, hash mismatch, or filesystem
            error.
    """

    ver = version or JarVersion.load()
    target = Path(install_path) if install_path else _DEFAULT_INSTALL_PATH

    if target.exists() and not force:
        try:
            if verify_jar(target, ver.sha256):
                logger.info("JAR already installed and verified (%s, sha256 ok).", target)
                return target
            logger.warning("Existing JAR at %s failed hash check; re-downloading.", target)
        except OSError as exc:
            logger.warning("Could not hash existing JAR (%s); re-downloading.", exc)

    target.parent.mkdir(parents=True, exist_ok=True)
    url = url_override or os.environ.get("DOMO_JAR_URL") or ver.url

    logger.info("Downloading Domo CLI JAR: %s (version %s)", url, ver.version)

    with tempfile.TemporaryDirectory(prefix="domojar_") as tmp:
        tmp_path = Path(tmp) / ver.filename
        try:
            (fetch or _default_fetch)(url, tmp_path)
        except Exception as exc:
            raise JarDownloadError(f"Failed to download {url}: {exc}") from exc

        try:
            actual = sha256_file(tmp_path).lower()
        except OSError as exc:
            raise JarDownloadError(f"Failed to hash downloaded JAR: {exc}") from exc

        if actual != ver.sha256.lower():
            raise JarDownloadError(
                f"Downloaded JAR hash mismatch. "
                f"Expected {ver.sha256}, got {actual}. Refusing to install."
            )

        shutil.move(str(tmp_path), str(target))
        logger.info("Installed JAR -> %s", target)
        return target


def _default_fetch(url: str, dest_path: Path) -> None:
    """Default HTTPS fetcher -- streams to disk using :mod:`urllib`."""

    with urllib.request.urlopen(url) as response, open(dest_path, "wb") as out:
        shutil.copyfileobj(response, out)


# ---------------------------------------------------------------------------
# Public helpers reused by the CLI + doctor
# ---------------------------------------------------------------------------


def default_install_path() -> Path:
    """Default install path (``app/utils/domoUtil.jar``)."""

    return _DEFAULT_INSTALL_PATH


def describe_version() -> str:
    """Human-readable version string, for logging / doctor output."""

    try:
        ver = JarVersion.load()
    except JarDownloadError:
        return "unknown"
    return f"{ver.version} (sha256={ver.sha256[:12]}...)"
