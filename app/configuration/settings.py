"""Centralized settings loaded from ``.env.<APP_ENV>`` files.

Loading priority for any key:
    1. Real OS environment variable
    2. Value from ``.env.<APP_ENV>`` (e.g. ``.env.local``)
    3. The default passed to :func:`get_env`
    4. ``None`` (or raise if ``required=True``)

Loading is idempotent and lazy -- ``load_dotenv`` is called the first time
:func:`get_env` runs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TypeVar, overload, Literal

from dotenv import load_dotenv

T = TypeVar("T")

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_loaded = False


class ConfigError(RuntimeError):
    """Raised when a required configuration value is missing."""


def _load_env_files() -> None:
    """Load ``.env.<APP_ENV>`` (and a fallback ``.env``) into ``os.environ``."""

    global _loaded
    if _loaded:
        return

    app_env = os.getenv("APP_ENV", "local").lower()
    candidates = [_REPO_ROOT / f".env.{app_env}", _REPO_ROOT / ".env"]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate, override=False)

    _loaded = True


@overload
def get_env(key: str, default: T, required: bool = False) -> str | T: ...


@overload
def get_env(key: str, *, required: Literal[True]) -> str: ...


@overload
def get_env(key: str, default: None = None, required: Literal[False] = False) -> str | None: ...


def get_env(
    key: str,
    default: T | None = None,
    required: bool = False,
) -> str | T | None:
    """Return the env var ``key``, or ``default``, or raise if ``required``."""

    _load_env_files()
    value = os.getenv(key)
    if value is not None and value != "":
        return value
    if required:
        raise ConfigError(
            f"Missing required configuration {key!r}. Set it in your environment "
            f"or in .env.{os.getenv('APP_ENV', 'local')}."
        )
    return default


def app_env() -> str:
    """Return the current ``APP_ENV`` value (default ``'local'``)."""

    _load_env_files()
    return os.getenv("APP_ENV", "local").lower()
