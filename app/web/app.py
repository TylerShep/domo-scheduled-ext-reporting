"""FastAPI factory -- wires config, routes, templates, static files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Install the [web] extras to use the web UI "
        "(pip install 'domo-scheduled-ext-reporting[web]')."
    ) from exc

from app.web.auth import SessionSigner
from app.web.config import WebConfig
from app.web.deps import (
    current_user_or_none,
)
from app.web.routes import (
    auth_router,
    destinations_router,
    health_router,
    reports_router,
    runs_router,
)
from app.web.storage import YamlStore

_THIS_DIR = Path(__file__).resolve().parent
_TEMPLATES_DIR = _THIS_DIR / "templates"
_STATIC_DIR = _THIS_DIR / "static"


def create_app(config: WebConfig | None = None) -> FastAPI:
    cfg = config or WebConfig.from_env()

    app = FastAPI(
        title="Domo Scheduled Reporting",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
    )

    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    templates.env.globals["app_title"] = "Domo Reporting"

    signer = SessionSigner(cfg.session_secret, cfg.session_max_age_seconds)
    store = YamlStore(cfg.reports_dir)

    app.state.web_config = cfg
    app.state.yaml_store = store
    app.state.session_signer = signer
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Auth + CRUD + health
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(reports_router)
    app.include_router(runs_router)
    app.include_router(destinations_router)

    @app.middleware("http")
    async def add_csrf_cookie(request: Request, call_next: Any):
        response = await call_next(request)
        csrf = request.cookies.get(cfg.csrf_cookie)
        if not csrf:
            import secrets

            new_token = secrets.token_urlsafe(24)
            response.set_cookie(
                key=cfg.csrf_cookie,
                value=new_token,
                httponly=False,
                samesite="lax",
            )
        return response

    @app.get("/", include_in_schema=False)
    def root(request: Request):
        user = current_user_or_none(request, signer, cfg)
        if user is None:
            return RedirectResponse("/login", status_code=307)
        return RedirectResponse("/reports", status_code=307)

    return app
