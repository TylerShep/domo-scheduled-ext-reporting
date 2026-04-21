"""FastAPI dependency providers for the web UI."""

from __future__ import annotations

import secrets
from typing import Any

try:
    from fastapi import Depends, HTTPException, Request, status
    from fastapi.templating import Jinja2Templates
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Install the [web] extras to use the web UI "
        "(pip install 'domo-scheduled-ext-reporting[web]')."
    ) from exc

from app.web.auth import SessionSigner, SessionUser, csrf_tokens_match
from app.web.config import WebConfig
from app.web.storage import YamlStore


def get_config(request: Request) -> WebConfig:
    return request.app.state.web_config  # type: ignore[no-any-return]


def get_store(request: Request) -> YamlStore:
    return request.app.state.yaml_store  # type: ignore[no-any-return]


def get_signer(request: Request) -> SessionSigner:
    return request.app.state.session_signer  # type: ignore[no-any-return]


def get_templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates  # type: ignore[no-any-return]


def current_user_or_none(
    request: Request,
    signer: SessionSigner = Depends(get_signer),
    config: WebConfig = Depends(get_config),
) -> SessionUser | None:
    token = request.cookies.get(config.session_cookie)
    return signer.verify(token)


def require_current_user(
    request: Request,
    user: SessionUser | None = Depends(current_user_or_none),
) -> SessionUser:
    if user is None:
        # A non-JSON GET gets redirected to /login so a human browser lands
        # on the login form; an XHR / JSON client gets a plain 401 so it can
        # react without its fetch being blindly redirected.
        accept = request.headers.get("accept", "").lower()
        wants_json = "application/json" in accept and "text/html" not in accept
        if request.method == "GET" and not wants_json:
            raise HTTPException(
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Location": "/login"},
                detail="Not authenticated",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def ensure_csrf_cookie(request: Request, response_headers: dict[str, Any]) -> str:
    """Return the existing CSRF cookie or generate a new one."""

    config: WebConfig = request.app.state.web_config
    existing = request.cookies.get(config.csrf_cookie)
    if existing:
        return existing
    new_token = secrets.token_urlsafe(24)
    response_headers["Set-Cookie"] = (
        f"{config.csrf_cookie}={new_token}; Path=/; SameSite=Lax; HttpOnly"
    )
    return new_token


def require_csrf(
    request: Request,
    config: WebConfig = Depends(get_config),
    x_csrf_token: str | None = None,
) -> None:
    """For mutating requests: require the double-submit token to match."""

    cookie_value = request.cookies.get(config.csrf_cookie)
    header_value = request.headers.get("x-csrf-token") or x_csrf_token
    form_value = None
    if not header_value:
        # Fall through to form body for classic HTML posts.
        ctype = request.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in ctype or "multipart/form-data" in ctype:
            form_value = request.scope.get("_parsed_csrf")
    submitted = header_value or form_value
    if not csrf_tokens_match(cookie_value, submitted):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid",
        )


async def parse_csrf_form(request: Request) -> None:
    """Middleware-ish helper to stash the form's csrf_token on the request."""

    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    ctype = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" not in ctype and "multipart/form-data" not in ctype:
        return
    try:
        form = await request.form()
    except Exception:
        return
    token = form.get("csrf_token")
    if token:
        request.scope["_parsed_csrf"] = str(token)


__all__ = [
    "get_config",
    "get_signer",
    "get_store",
    "get_templates",
    "current_user_or_none",
    "require_current_user",
    "require_csrf",
    "parse_csrf_form",
    "ensure_csrf_cookie",
]
