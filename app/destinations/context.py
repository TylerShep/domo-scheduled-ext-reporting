"""Build standard Jinja render contexts from destination contexts.

Centralised here so every destination's templates see the same variables
and filter set. Keeps Slack / Teams / Email / Email-caption surfaces
consistent.
"""

from __future__ import annotations

import datetime
from typing import Any

from app.destinations.base import DatasetContext, DestinationContext


def _today_ctx() -> dict[str, Any]:
    now = datetime.datetime.now()
    return {
        "today": now.date().isoformat(),
        "now": now.isoformat(timespec="seconds"),
    }


def card_context(ctx: DestinationContext, **extra: Any) -> dict[str, Any]:
    """Return a render context for a single card send."""

    base = _today_ctx()
    base["card"] = {
        "name": ctx.card_name,
        "url": ctx.card_url,
        "page_name": ctx.page_name,
        "image_path": ctx.image_path,
    }
    base["card_name"] = ctx.card_name
    base["card_url"] = ctx.card_url
    base["page_name"] = ctx.page_name
    if ctx.extra:
        base["extra"] = dict(ctx.extra)
    base.update(extra)
    return base


def dataset_context(ctx: DatasetContext, **extra: Any) -> dict[str, Any]:
    """Return a render context for a dataset send."""

    base = _today_ctx()
    base["dataset"] = {
        "name": ctx.dataset_name,
        "id": ctx.dataset_id,
        "format": ctx.file_format,
        "path": ctx.file_path,
    }
    base["dataset_name"] = ctx.dataset_name
    base["dataset_id"] = ctx.dataset_id
    if ctx.extra:
        base["extra"] = dict(ctx.extra)
    base.update(extra)
    return base
