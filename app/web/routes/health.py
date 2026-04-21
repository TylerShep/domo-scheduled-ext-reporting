"""Health + metrics endpoints (no auth required)."""

from __future__ import annotations

from fastapi import APIRouter, Response

from app.observability.metrics import render_text

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/metrics")
def metrics() -> Response:
    data, content_type = render_text()
    return Response(content=data, media_type=content_type)
