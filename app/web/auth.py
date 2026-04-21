"""Password hashing + session cookie helpers for the web UI.

Design notes
------------

* **Single admin user** out of the box. Most teams run this behind a corporate
  SSO proxy / Tailscale / VPN, so rolling a full user table would be
  over-engineering. A single hashed password (Argon2) is plenty.

* **Stateless signed session** -- we use :mod:`itsdangerous` to sign
  `{"u": "<username>"}` and put the token in an HTTP-only cookie. No server-side
  session table means the UI is horizontally scalable without a sticky session.

* **CSRF** -- for mutating requests we require a double-submit cookie. The
  cookie is set on first visit, and the same value must be sent via the
  ``X-CSRF-Token`` header or a hidden form field.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any

try:
    from itsdangerous import BadSignature, URLSafeTimedSerializer
    from passlib.context import CryptContext
except ImportError as exc:  # pragma: no cover - graceful degradation
    raise ImportError(
        "Optional web dependencies are not installed. Install with "
        "`pip install 'domo-scheduled-ext-reporting[web]'`."
    ) from exc


_pwd = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Hash a plaintext password using Argon2id (scrypt-like, memory-hard)."""

    if not plain:
        raise ValueError("password cannot be empty")
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Constant-time verify the plaintext against a hash."""

    if not hashed:
        return False
    try:
        return _pwd.verify(plain, hashed)
    except Exception:  # pragma: no cover - defensive
        return False


@dataclass(frozen=True)
class SessionUser:
    """Minimal principal carried in the signed session cookie."""

    username: str


class SessionSigner:
    """Wraps :class:`URLSafeTimedSerializer` for session token encode/decode."""

    _SALT = "domo-reporting-session"

    def __init__(self, secret: str, max_age_seconds: int) -> None:
        if not secret:
            raise ValueError("session secret must not be empty")
        self._signer = URLSafeTimedSerializer(secret, salt=self._SALT)
        self._max_age = max_age_seconds

    def sign(self, username: str) -> str:
        return self._signer.dumps({"u": username})

    def verify(self, token: str | None) -> SessionUser | None:
        if not token:
            return None
        try:
            payload: Any = self._signer.loads(token, max_age=self._max_age)
        except BadSignature:
            return None
        if not isinstance(payload, dict):
            return None
        username = payload.get("u")
        if not isinstance(username, str) or not username:
            return None
        return SessionUser(username=username)


def csrf_tokens_match(cookie_value: str | None, submitted: str | None) -> bool:
    """Double-submit cookie check -- both values must match, constant-time."""

    if not cookie_value or not submitted:
        return False
    return hmac.compare_digest(cookie_value, submitted)
