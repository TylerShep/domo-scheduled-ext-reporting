"""Shared Jinja2 templating engine with reporting-specific filters.

Every destination (Slack initial_comment, Teams chatMessage, Email
subject/body, card captions, etc.) goes through this single env so users
get the same filter set and consistent error behaviour -- in particular,
:class:`jinja2.StrictUndefined` is enabled so typos like ``{{ card.neme }}``
raise instead of silently rendering an empty string.

Custom filters:

    * ``currency`` -- ``{{ 1234.5|currency }}`` -> ``"$1,234.50"``
      Optional ``symbol`` arg: ``{{ 1234|currency("£") }}`` -> ``"£1,234.00"``.
    * ``pct``      -- ``{{ 0.425|pct }}`` -> ``"42.50%"``
      Optional ``digits`` arg.
    * ``delta``    -- ``{{ 0.08|delta }}`` -> ``"+8.0%"`` (ratio input).
    * ``human_number`` -- ``{{ 12_500|human_number }}`` -> ``"12.5K"``.

Available context keys you can pass at render time:

    * ``today``  -- ``datetime.date``  -- run date (UTC).
    * ``now``    -- ``datetime`` -- run start (UTC).
    * ``report`` -- dict with at least ``name``.
    * ``card``   -- dict with ``name``, ``url``, ``page_name`` (per-card).
    * ``cards``  -- list of card dicts.
    * ``dataset``/``datasets`` -- same shape as their card counterpart.
    * Plus anything else the caller chooses to pass.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

from jinja2 import Environment, StrictUndefined

from app.utils.logger import get_logger

logger = get_logger(__name__)


class TemplateError(RuntimeError):
    """Raised when a template render fails (bad syntax, undefined variable)."""


_DEFAULT_CURRENCY = "$"
_HUMAN_SUFFIXES = [(1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")]


def currency(value: Any, symbol: str = _DEFAULT_CURRENCY, digits: int = 2) -> str:
    """Format ``value`` as a currency string: ``$1,234.56``."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return str(value)
    return f"{symbol}{number:,.{digits}f}"


def pct(value: Any, digits: int = 2, as_ratio: bool = True) -> str:
    """Format ``value`` as a percentage string.

    When ``as_ratio`` is True (default) the input is multiplied by 100
    (``0.425`` -> ``"42.50%"``). Pass ``as_ratio=False`` for inputs that
    are already percentages (``42.5`` -> ``"42.50%"``).
    """

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return str(value)
    if as_ratio:
        number *= 100.0
    return f"{number:.{digits}f}%"


def delta(value: Any, digits: int = 1, as_ratio: bool = True) -> str:
    """Format ``value`` as a signed percentage: ``+8.0%`` / ``-3.2%``.

    Useful for period-over-period comparisons. Returns ``"flat"`` for zero.
    """

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return str(value)
    if number == 0:
        return "flat"
    if as_ratio:
        number *= 100.0
    sign = "+" if number > 0 else "-"
    return f"{sign}{abs(number):.{digits}f}%"


def human_number(value: Any, digits: int = 1) -> str:
    """Return ``12500`` -> ``"12.5K"``, ``3_250_000`` -> ``"3.3M"``."""

    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(number) or math.isinf(number):
        return str(value)
    abs_number = abs(number)
    for threshold, suffix in _HUMAN_SUFFIXES:
        if abs_number >= threshold:
            scaled = number / threshold
            return f"{scaled:.{digits}f}{suffix}"
    return f"{number:.{digits}f}" if abs_number < 1 else f"{int(number)}"


_FILTERS: dict[str, Any] = {
    "currency": currency,
    "pct": pct,
    "delta": delta,
    "human_number": human_number,
}


def build_environment(*, autoescape: bool = False) -> Environment:
    """Return a fresh :class:`jinja2.Environment` wired with our filters."""

    env = Environment(
        autoescape=autoescape,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(_FILTERS)
    return env


def render(
    template: str,
    context: dict[str, Any],
    *,
    autoescape: bool = False,
    extra_filters: Iterable[tuple[str, Any]] | None = None,
) -> str:
    """Render ``template`` against ``context`` and return the result.

    Raises :class:`TemplateError` on any Jinja2 failure so callers can
    handle it with a single ``except`` clause.
    """

    env = build_environment(autoescape=autoescape)
    if extra_filters:
        for name, func in extra_filters:
            env.filters[name] = func
    try:
        return env.from_string(template).render(**context)
    except Exception as exc:  # noqa: BLE001 -- we want all Jinja errors here
        raise TemplateError(f"Template render failed: {exc}") from exc


def render_safe(
    template: str,
    context: dict[str, Any],
    *,
    fallback: str | None = None,
    autoescape: bool = False,
) -> str:
    """Like :func:`render` but returns ``fallback`` (or the raw template)
    when the render fails -- useful for non-critical surfaces like captions
    where we'd rather ship the raw text than crash a whole report.
    """

    try:
        return render(template, context, autoescape=autoescape)
    except TemplateError as exc:
        logger.warning("Template render failed, using fallback: %s", exc)
        return fallback if fallback is not None else template
