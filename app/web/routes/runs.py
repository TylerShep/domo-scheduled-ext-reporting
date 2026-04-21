"""Run history endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.history.registry import get_backend
from app.web.auth import SessionUser
from app.web.deps import get_templates, require_current_user

router = APIRouter(prefix="/runs", tags=["runs"])


def _backend():
    return get_backend()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def list_runs(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    user: SessionUser = Depends(require_current_user),
    report: str | None = None,
    limit: int = 100,
):
    backend = _backend()
    runs = backend.get_runs(report_name=report, limit=max(1, min(limit, 500)))
    return templates.TemplateResponse(
        request,
        "runs/list.html",
        {
            "runs": runs,
            "filter_report": report or "",
            "user": user,
        },
    )


@router.get("/{run_id}", response_class=HTMLResponse)
def show_run(
    run_id: str,
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    user: SessionUser = Depends(require_current_user),
):
    backend = _backend()
    run = backend.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found")
    return templates.TemplateResponse(
        request,
        "runs/show.html",
        {"run": run, "user": user},
    )
