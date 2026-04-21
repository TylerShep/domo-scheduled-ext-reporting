"""Login / logout routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.web.auth import SessionSigner, verify_password
from app.web.config import WebConfig
from app.web.deps import get_config, get_signer, get_templates

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_form(
    request: Request,
    templates: Jinja2Templates = Depends(get_templates),
):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
def login_submit(
    request: Request,
    response: Response,
    username: str = Form(""),
    password: str = Form(""),
    config: WebConfig = Depends(get_config),
    signer: SessionSigner = Depends(get_signer),
    templates: Jinja2Templates = Depends(get_templates),
):
    expected_user = config.admin_username
    stored_hash = config.admin_password_hash
    matches_plain = (
        config.admin_password_plain is not None and config.admin_password_plain == password
    )
    matches_hash = verify_password(password, stored_hash) if stored_hash else False
    if username != expected_user or not (matches_hash or matches_plain):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid credentials"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    token = signer.sign(expected_user)
    resp = RedirectResponse("/reports", status_code=status.HTTP_303_SEE_OTHER)
    resp.set_cookie(
        key=config.session_cookie,
        value=token,
        max_age=config.session_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=False,
    )
    return resp


@router.post("/logout")
def logout(
    config: WebConfig = Depends(get_config),
):
    resp = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie(config.session_cookie)
    return resp
