"""Destination diagnostics routes.

These helpers let an operator poke at a destination spec before committing it
to a YAML file.  The endpoints run a minimal ``prepare()`` against whatever
was submitted, but never send any real traffic to Slack / Teams / etc.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse

from app.destinations.registry import build_destination
from app.web.auth import SessionUser
from app.web.config import WebConfig
from app.web.deps import get_config, parse_csrf_form, require_csrf, require_current_user

router = APIRouter(prefix="/destinations", tags=["destinations"])


@router.post(
    "/test",
    dependencies=[Depends(parse_csrf_form), Depends(require_csrf)],
)
def test_destination(
    spec: dict[str, Any] = Body(...),
    user: SessionUser = Depends(require_current_user),
    config: WebConfig = Depends(get_config),
):
    if not config.allow_destination_tests:
        raise HTTPException(status_code=403, detail="destination tests are disabled")
    if not isinstance(spec, dict):
        raise HTTPException(status_code=400, detail="expected a JSON object")
    try:
        destination = build_destination({**spec, "dry_run": True})
    except Exception as exc:  # noqa: BLE001 - surface validation error to operator
        return JSONResponse({"ok": False, "error": f"build: {exc}"}, status_code=400)
    try:
        destination.prepare()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"prepare: {exc}"}, status_code=400)
    return {"ok": True, "destination": destination.describe()}
