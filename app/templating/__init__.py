"""Shared Jinja2 templating engine used by captions, email bodies, and Teams cards."""

from app.templating.engine import (
    TemplateError,
    build_environment,
    render,
    render_safe,
)

__all__ = [
    "TemplateError",
    "build_environment",
    "render",
    "render_safe",
]
