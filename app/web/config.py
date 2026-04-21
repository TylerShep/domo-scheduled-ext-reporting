"""Web UI configuration read from environment variables.

All values have sensible defaults so the UI boots out-of-the-box, but every
single one can be overridden via environment variable -- perfect for Docker.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, "").strip()
    return value or default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ""))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class WebConfig:
    """Resolved web UI settings."""

    reports_dir: Path
    session_secret: str
    session_cookie: str
    session_max_age_seconds: int
    admin_username: str
    admin_password_hash: str | None
    admin_password_plain: str | None
    csrf_cookie: str
    allow_destination_tests: bool
    bind_host: str
    bind_port: int

    @classmethod
    def from_env(cls) -> WebConfig:
        reports_dir_str = _env("DOMO_WEB_REPORTS_DIR", str(_REPO_ROOT / "config" / "reports"))
        reports_dir = Path(reports_dir_str).expanduser().resolve()
        session_secret = _env("DOMO_WEB_SESSION_SECRET", secrets.token_urlsafe(32))
        session_cookie = _env("DOMO_WEB_SESSION_COOKIE", "domo_session")
        session_max_age = _env_int("DOMO_WEB_SESSION_TTL", 60 * 60 * 8)  # 8 hours
        admin_user = _env("DOMO_WEB_ADMIN_USER", "admin")
        admin_hash = os.environ.get("DOMO_WEB_ADMIN_PASSWORD_HASH", "").strip() or None
        admin_plain = os.environ.get("DOMO_WEB_ADMIN_PASSWORD", "").strip() or None
        csrf_cookie = _env("DOMO_WEB_CSRF_COOKIE", "domo_csrf")
        allow_tests = _env_bool("DOMO_WEB_ALLOW_DESTINATION_TESTS", True)
        bind_host = _env("DOMO_WEB_HOST", "127.0.0.1")
        bind_port = _env_int("DOMO_WEB_PORT", 8080)
        return cls(
            reports_dir=reports_dir,
            session_secret=session_secret,
            session_cookie=session_cookie,
            session_max_age_seconds=session_max_age,
            admin_username=admin_user,
            admin_password_hash=admin_hash,
            admin_password_plain=admin_plain,
            csrf_cookie=csrf_cookie,
            allow_destination_tests=allow_tests,
            bind_host=bind_host,
            bind_port=bind_port,
        )
