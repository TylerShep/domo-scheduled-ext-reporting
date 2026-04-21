"""Reports CRUD endpoints: list / view / create / update / delete / validate.

Route declaration order matters here: ``/validate`` must be registered before
the catch-all ``/{filename}`` or requests to ``/reports/validate`` will be
routed to the update handler with ``filename="validate"``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.web.auth import SessionUser
from app.web.deps import (
    get_store,
    get_templates,
    parse_csrf_form,
    require_csrf,
    require_current_user,
)
from app.web.storage import YamlStore, YamlStoreError

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def list_reports(
    request: Request,
    store: YamlStore = Depends(get_store),
    templates: Jinja2Templates = Depends(get_templates),
    user: SessionUser = Depends(require_current_user),
):
    summaries = store.list_summaries()
    return templates.TemplateResponse(
        request,
        "reports/list.html",
        {"summaries": summaries, "user": user},
    )


@router.get("/new", response_class=HTMLResponse)
def new_report(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
    user: SessionUser = Depends(require_current_user),
):
    return templates.TemplateResponse(
        request,
        "reports/edit.html",
        {
            "filename": "",
            "text": _DEFAULT_SKELETON,
            "is_new": True,
            "error": None,
            "user": user,
        },
    )


@router.post(
    "/validate",
    dependencies=[Depends(parse_csrf_form), Depends(require_csrf)],
)
async def validate_report(
    request: Request,
    store: YamlStore = Depends(get_store),
    user: SessionUser = Depends(require_current_user),
):
    """Validate a YAML document without persisting it.

    Accepts either JSON (``{"content": "..."}``) or a form body with a
    ``content`` field so both the Alpine.js front-end and ``curl`` users work.
    """

    text: str | None = None
    ctype = request.headers.get("content-type", "")
    if "application/json" in ctype:
        try:
            payload = await request.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            text = payload.get("content")
    else:
        form = await request.form()
        value = form.get("content")
        text = str(value) if value is not None else None

    if not text:
        return JSONResponse({"ok": False, "error": "content required"}, status_code=400)
    try:
        data = store.validate_text(text)
    except YamlStoreError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "report_name": str(data.get("name") or "")})


@router.post(
    "",
    response_class=HTMLResponse,
    dependencies=[Depends(parse_csrf_form), Depends(require_csrf)],
)
def create_report(
    request: Request,
    filename: str = Form(...),
    content: str = Form(...),
    store: YamlStore = Depends(get_store),
    templates: Jinja2Templates = Depends(get_templates),
    user: SessionUser = Depends(require_current_user),
):
    try:
        store.write_text(filename, content, overwrite=False)
    except YamlStoreError as exc:
        return templates.TemplateResponse(
            request,
            "reports/edit.html",
            {
                "filename": filename,
                "text": content,
                "is_new": True,
                "error": str(exc),
                "user": user,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(f"/reports/{filename}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/{filename}", response_class=HTMLResponse)
def edit_report(
    filename: str,
    request: Request,
    store: YamlStore = Depends(get_store),
    templates: Jinja2Templates = Depends(get_templates),
    user: SessionUser = Depends(require_current_user),
):
    try:
        text = store.read_text(filename)
    except YamlStoreError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request,
        "reports/edit.html",
        {
            "filename": filename,
            "text": text,
            "is_new": False,
            "error": None,
            "user": user,
        },
    )


@router.post(
    "/{filename}",
    response_class=HTMLResponse,
    dependencies=[Depends(parse_csrf_form), Depends(require_csrf)],
)
def update_report(
    filename: str,
    request: Request,
    content: str = Form(...),
    store: YamlStore = Depends(get_store),
    templates: Jinja2Templates = Depends(get_templates),
    user: SessionUser = Depends(require_current_user),
):
    try:
        store.write_text(filename, content, overwrite=True)
    except YamlStoreError as exc:
        return templates.TemplateResponse(
            request,
            "reports/edit.html",
            {
                "filename": filename,
                "text": content,
                "is_new": False,
                "error": str(exc),
                "user": user,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(f"/reports/{filename}", status_code=status.HTTP_303_SEE_OTHER)


@router.post(
    "/{filename}/delete",
    dependencies=[Depends(parse_csrf_form), Depends(require_csrf)],
)
def delete_report(
    filename: str,
    store: YamlStore = Depends(get_store),
    user: SessionUser = Depends(require_current_user),
):
    try:
        store.delete(filename)
    except YamlStoreError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return RedirectResponse("/reports", status_code=status.HTTP_303_SEE_OTHER)


_DEFAULT_SKELETON = """name: example_report
metadata_dataset_file_name: example_report
schedule: "0 13 * * *"

cards:
  - dashboard: "Your Dashboard"
    card: "Your Card"
    viz_type: "Single Value"

destinations:
  - type: slack
    channel_name: "your-channel"
"""
