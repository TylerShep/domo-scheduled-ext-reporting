"""Pluggable destination interface.

A *destination* is anywhere a generated card image (or, in the future, a
dataset file) can be sent: a Slack channel, a Microsoft Teams channel via
Graph API, a Teams webhook, etc.

To add a new destination:
    1. Subclass :class:`Destination` and implement :meth:`send_image`.
    2. Register it in ``app/destinations/registry.py``.
    3. Reference it from a YAML report by ``type: <your_key>``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DestinationContext:
    """Information passed to :meth:`Destination.send_image` per card."""

    image_path: str
    card_name: str
    card_url: str
    page_name: str
    extra: dict[str, Any] = field(default_factory=dict)


class Destination(ABC):
    """Base class every destination implementation inherits from."""

    #: Unique key used in YAML ``type:`` and the destination registry.
    key: str = ""

    #: Human-friendly label that appears in logs.
    label: str = ""

    def __init__(self, **config: Any) -> None:
        self.config = config

    @abstractmethod
    def send_image(self, ctx: DestinationContext) -> None:
        """Send a single card image. Implementations should raise on failure."""

    def prepare(self) -> None:
        """Optional one-time setup before the first :meth:`send_image` call.

        Useful for resolving channel IDs / acquiring auth tokens. Default is
        a no-op.
        """

    def teardown(self) -> None:
        """Optional cleanup after all sends complete. Default is a no-op."""

    def describe(self) -> str:
        """Short string describing this destination for log lines."""

        return f"{self.label or self.key}({self.config})"
