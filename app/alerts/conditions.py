"""Evaluate ``send_when:`` expressions in a sandboxed :mod:`asteval` interpreter.

Design goals
------------

* **Safety first** -- no ``os.system``, no ``__import__``, no dunder access,
  no network, no filesystem.  We rely on :mod:`asteval` to block these and
  then *also* hard-code a deny-list because defense-in-depth is cheap.
* **Booleanish results** -- a non-boolean return value coerces sensibly
  (``0``/``""``/``None``/``[]`` -> False; anything else -> True).  Syntax
  errors or exceptions raised inside the expression fall back to *allow
  sending* by default -- the goal is not to silently drop cards because a
  typo slipped into a condition.
* **Stateless** -- every :func:`evaluate` call builds a fresh interpreter
  so previously assigned variables (``x = 1``) don't leak between cards.

Typical call site::

    from app.alerts import should_send, build_card_context
    ctx = build_card_context(card_item, run)
    if not should_send(card.get("send_when"), ctx):
        continue
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)

try:
    from asteval import Interpreter  # type: ignore[import-not-found]

    _ASTEVAL_AVAILABLE = True
except ImportError:  # pragma: no cover - asteval is a required dep
    Interpreter = None  # type: ignore[assignment]
    _ASTEVAL_AVAILABLE = False


class AlertError(Exception):
    """Raised for malformed expressions we refuse to even evaluate."""


@dataclass
class ConditionResult:
    """Outcome of a single ``send_when`` evaluation.

    Attributes:
        allowed: Final boolean the caller should act on.
        expression: The raw expression string (for logs).
        reason: Short human-friendly label ("no-expression", "truthy",
            "falsy", "error", "refused").
        error: Set when an expression raised or failed to parse.
    """

    allowed: bool
    expression: str | None = None
    reason: str = ""
    error: str | None = None


#: Substrings that make us refuse to even try evaluating (belt-and-suspenders
#: on top of asteval's own sandbox).
_REFUSED_TOKENS = (
    "__",  # dunders -- blocks __import__, __class__, __builtins__, ...
    "import ",
    "exec(",
    "eval(",
    "open(",
    "compile(",
    "globals(",
    "locals(",
    "getattr(",
    "setattr(",
    "delattr(",
    "vars(",
    "input(",
    "subprocess",
    "os.system",
    "os.popen",
)


def _refuse(expression: str) -> str | None:
    lowered = expression.lower()
    for token in _REFUSED_TOKENS:
        if token in lowered:
            return token
    return None


def evaluate(
    expression: str | None,
    context: Mapping[str, Any] | None = None,
) -> ConditionResult:
    """Evaluate a ``send_when`` expression against a variable context.

    Args:
        expression: The raw expression string (or ``None``/empty -- always
            allowed).
        context: Mapping of names the expression may reference.

    Returns:
        A :class:`ConditionResult` with ``allowed`` set.  On *any* unexpected
        failure we log and return ``allowed=True`` so broken conditions don't
        silently suppress alerts.
    """

    if expression is None or not str(expression).strip():
        return ConditionResult(allowed=True, expression=None, reason="no-expression")

    expr_str = str(expression).strip()

    refused = _refuse(expr_str)
    if refused is not None:
        logger.warning(
            "Refusing to evaluate send_when expression containing %r: %s",
            refused,
            expr_str,
        )
        return ConditionResult(
            allowed=True,
            expression=expr_str,
            reason="refused",
            error=f"expression contains forbidden token: {refused!r}",
        )

    if not _ASTEVAL_AVAILABLE:  # pragma: no cover
        logger.warning("asteval not installed; skipping send_when evaluation.")
        return ConditionResult(allowed=True, expression=expr_str, reason="no-engine")

    try:
        interp = Interpreter(
            use_numpy=False,
            minimal=True,
        )
    except TypeError:
        # Older / different asteval versions reject ``minimal``; fall back.
        interp = Interpreter(use_numpy=False)

    if context:
        # Wrap any plain dicts in DotDict so expressions can do ``card.value``
        # in addition to ``card['value']``.
        from app.alerts.context import DotDict

        for key, value in context.items():
            if isinstance(value, dict) and not isinstance(value, DotDict):
                interp.symtable[key] = DotDict(value)
            else:
                interp.symtable[key] = value

    try:
        result = interp(expr_str)
    except Exception as exc:  # pragma: no cover - asteval collects errors internally
        logger.warning("send_when expression raised: %s -- %s", expr_str, exc)
        return ConditionResult(
            allowed=True,
            expression=expr_str,
            reason="error",
            error=str(exc)[:500],
        )

    if interp.error:
        err_msg = "; ".join(str(e.get_error()) for e in interp.error)
        logger.warning("send_when expression failed to parse: %s -- %s", expr_str, err_msg)
        return ConditionResult(
            allowed=True,
            expression=expr_str,
            reason="error",
            error=err_msg[:500],
        )

    allowed = bool(result)
    return ConditionResult(
        allowed=allowed,
        expression=expr_str,
        reason="truthy" if allowed else "falsy",
    )


def should_send(
    expression: str | None,
    context: Mapping[str, Any] | None = None,
) -> bool:
    """Convenience wrapper that returns just the boolean result."""

    return evaluate(expression, context).allowed
