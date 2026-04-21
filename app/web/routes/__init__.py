"""Route modules for the web UI."""

from __future__ import annotations

from app.web.routes.auth import router as auth_router
from app.web.routes.destinations import router as destinations_router
from app.web.routes.health import router as health_router
from app.web.routes.reports import router as reports_router
from app.web.routes.runs import router as runs_router

__all__ = [
    "auth_router",
    "destinations_router",
    "health_router",
    "reports_router",
    "runs_router",
]
