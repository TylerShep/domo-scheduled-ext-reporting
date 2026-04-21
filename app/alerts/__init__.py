"""Sandboxed ``send_when:`` expression engine.

YAML reports can gate delivery at two levels:

* **Card-level** -- ``send_when:`` on a card dict, evaluated once per card.
  If false, *no* destination receives that card.
* **Destination-level** -- ``send_when:`` on a destination spec, evaluated
  once per ``(card, destination)`` pair. Lets you fan different cards out
  to different channels.

Expressions are plain Python (``card.value > 1000 and run.status == 'success'``)
evaluated inside :mod:`asteval`'s sandbox -- no file / network / import
access.  See :mod:`app.alerts.conditions` for the evaluator and
:mod:`app.alerts.context` for the variables available to an expression.
"""

from __future__ import annotations

from app.alerts.conditions import (
    AlertError,
    ConditionResult,
    evaluate,
    should_send,
)
from app.alerts.context import build_card_context, build_dataset_context

__all__ = [
    "AlertError",
    "ConditionResult",
    "evaluate",
    "should_send",
    "build_card_context",
    "build_dataset_context",
]
