"""Factory mapping a YAML ``type:`` string to a :class:`Destination`.

To register a custom destination, call :func:`register_destination` at
import time (e.g. from your project's ``main.py`` or a service module).
"""

from __future__ import annotations

from collections.abc import Callable

from app.destinations.base import Destination
from app.destinations.email import EmailDestination
from app.destinations.file import FileDestination
from app.destinations.slack import SlackDestination
from app.destinations.teams import make_teams_destination

DestinationFactory = Callable[..., Destination]


_REGISTRY: dict[str, DestinationFactory] = {
    "slack": SlackDestination,
    "teams": make_teams_destination,
    "file": FileDestination,
    "email": EmailDestination,
}


def register_destination(key: str, factory: DestinationFactory) -> None:
    """Register or override a destination type."""

    _REGISTRY[key.lower()] = factory


def build_destination(spec: dict) -> Destination:
    """Build a :class:`Destination` from a YAML dict.

    The dict must include ``type``. All other keys become kwargs on the
    selected factory.

    Raises:
        KeyError: If ``type`` is missing or unknown.
    """

    if "type" not in spec:
        raise KeyError("Destination spec missing required 'type' key")

    spec = dict(spec)
    dest_type = str(spec.pop("type")).lower()
    try:
        factory = _REGISTRY[dest_type]
    except KeyError as exc:
        known = sorted(_REGISTRY.keys())
        raise KeyError(f"Unknown destination type {dest_type!r}; known types: {known}") from exc
    return factory(**spec)


def known_destination_types() -> list[str]:
    return sorted(_REGISTRY.keys())
