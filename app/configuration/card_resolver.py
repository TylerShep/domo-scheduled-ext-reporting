"""Resolve YAML ``cards_query:`` blocks into concrete card lists.

When a report declares::

    cards_query:
      page: "Sales KPIs"
      tags: ["daily"]
      exclude_tags: ["wip"]
      viz_type: "Single Value"   # optional default applied to every match
      limit: 20                  # optional cap

...the resolver:

1. Calls the active engine's :meth:`DomoEngine.list_cards` with the same
   filters. Results are cached on disk at
   ``app/state/discovery_cache.json`` with a TTL so we don't hammer Domo
   on every run.
2. Converts each :class:`CardSummary` into a ``cards:`` YAML row dict
   ``{"dashboard", "card", "viz_type"}`` compatible with the existing
   YAML loader / ``DomoBase.list_of_cards``.

Callers merge the resolved list with any explicit ``cards:`` entries.

Cache TTL is read from the ``DISCOVERY_CACHE_TTL_SECONDS`` env var
(default: 3600s = 1h). Passing ``force_refresh=True`` bypasses the cache
for a single call.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.configuration.settings import get_env
from app.engines import CardSummary, DomoEngine, get_engine
from app.utils.logger import get_logger

logger = get_logger(__name__)


_DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "state" / "discovery_cache.json"
_DEFAULT_TTL_SECONDS = 3600
_ALLOWED_QUERY_KEYS = {
    "page",
    "tags",
    "exclude_tags",
    "viz_type",
    "limit",
    "sort",
}


class CardResolverError(RuntimeError):
    """Raised when a ``cards_query`` block is malformed or cannot resolve."""


@dataclass
class ResolvedCard:
    """YAML-loader-compatible shape: same keys as a ``cards:`` entry."""

    dashboard: str
    card: str
    viz_type: str
    card_id: int | None = None
    card_url: str | None = None
    tags: list[str] = field(default_factory=list)

    def to_yaml_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "dashboard": self.dashboard,
            "card": self.card,
            "viz_type": self.viz_type,
        }
        if self.card_id is not None:
            out["card_id"] = self.card_id
        if self.card_url:
            out["card_url"] = self.card_url
        if self.tags:
            out["tags"] = list(self.tags)
        return out


def resolve_cards_query(
    query: dict[str, Any],
    *,
    engine: DomoEngine | None = None,
    cache_path: Path | None = None,
    ttl_seconds: int | None = None,
    force_refresh: bool = False,
) -> list[ResolvedCard]:
    """Return cards matching ``query``, using the disk cache when fresh."""

    _validate_query(query)

    cache_path = cache_path or _resolve_cache_path()
    ttl = ttl_seconds if ttl_seconds is not None else _resolve_ttl()
    cache_key = _cache_key(query)

    if not force_refresh:
        cached = _read_cache(cache_path, cache_key, ttl)
        if cached is not None:
            logger.debug("card_resolver cache hit for %s", cache_key)
            return [_card_from_cache(row) for row in cached]

    resolved = _fetch_from_engine(query, engine=engine)
    _write_cache(cache_path, cache_key, [r.__dict__ for r in resolved])
    logger.info(
        "card_resolver resolved %d card(s) via engine, cached at %s",
        len(resolved),
        cache_path,
    )
    return resolved


def clear_discovery_cache(cache_path: Path | None = None) -> None:
    """Erase the on-disk cache (useful for --refresh-cache CLI flag)."""

    cache_path = cache_path or _resolve_cache_path()
    if cache_path.exists():
        cache_path.unlink()
        logger.info("Cleared discovery cache at %s", cache_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_query(query: dict[str, Any]) -> None:
    if not isinstance(query, dict):
        raise CardResolverError(f"cards_query must be a mapping, got {type(query).__name__}")
    unknown = set(query.keys()) - _ALLOWED_QUERY_KEYS
    if unknown:
        raise CardResolverError(
            f"Unknown cards_query keys: {sorted(unknown)}. "
            f"Allowed: {sorted(_ALLOWED_QUERY_KEYS)}."
        )
    if "tags" in query and not _is_str_list(query["tags"]):
        raise CardResolverError("cards_query.tags must be a list of strings")
    if "exclude_tags" in query and not _is_str_list(query["exclude_tags"]):
        raise CardResolverError("cards_query.exclude_tags must be a list of strings")
    if "limit" in query and not isinstance(query["limit"], int):
        raise CardResolverError("cards_query.limit must be an integer")


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def _fetch_from_engine(
    query: dict[str, Any],
    engine: DomoEngine | None = None,
) -> list[ResolvedCard]:
    engine = engine or get_engine()
    try:
        summaries = engine.list_cards(
            page=query.get("page"),
            tags=query.get("tags"),
            exclude_tags=query.get("exclude_tags"),
        )
    except NotImplementedError as exc:
        raise CardResolverError(
            f"Active engine '{engine.describe()}' does not support card discovery "
            "(set DOMO_ENGINE=rest or expand the engine's list_cards())."
        ) from exc

    default_viz = query.get("viz_type", "")
    limit = int(query.get("limit", 0) or 0)
    resolved: list[ResolvedCard] = [
        _card_from_summary(s, default_viz=default_viz) for s in summaries
    ]
    if limit > 0:
        resolved = resolved[:limit]
    return resolved


def _card_from_summary(summary: CardSummary, *, default_viz: str = "") -> ResolvedCard:
    return ResolvedCard(
        dashboard=str(summary.page_name or summary.page_id or ""),
        card=str(summary.card_name or ""),
        viz_type=default_viz,
        card_id=summary.card_id,
        card_url=summary.card_url,
        tags=list(summary.tags),
    )


def _card_from_cache(row: dict[str, Any]) -> ResolvedCard:
    return ResolvedCard(
        dashboard=str(row.get("dashboard", "")),
        card=str(row.get("card", "")),
        viz_type=str(row.get("viz_type", "")),
        card_id=row.get("card_id"),
        card_url=row.get("card_url"),
        tags=list(row.get("tags", [])),
    )


def _cache_key(query: dict[str, Any]) -> str:
    canonical = json.dumps(query, sort_keys=True, default=str)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def _read_cache(path: Path, key: str, ttl: int) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Discovery cache at %s is corrupt; rebuilding.", path)
        return None

    entry = payload.get(key)
    if not isinstance(entry, dict):
        return None
    if time.time() - float(entry.get("written_at", 0)) > ttl:
        return None
    rows = entry.get("rows")
    if not isinstance(rows, list):
        return None
    return rows


def _write_cache(path: Path, key: str, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8")) or {}
        except json.JSONDecodeError:
            payload = {}
    payload[key] = {
        "written_at": time.time(),
        "rows": list(rows),
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _resolve_cache_path() -> Path:
    override = os.getenv("DISCOVERY_CACHE_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT_CACHE_PATH


def _resolve_ttl() -> int:
    raw = get_env("DISCOVERY_CACHE_TTL_SECONDS", default=str(_DEFAULT_TTL_SECONDS))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_SECONDS


def resolved_cards_to_yaml_rows(
    cards: Sequence[ResolvedCard],
) -> list[dict[str, Any]]:
    """Convert ``ResolvedCard`` rows to the YAML loader's ``cards:`` dict shape."""

    return [c.to_yaml_dict() for c in cards]
