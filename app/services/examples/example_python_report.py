"""Example Python-subclass report.

Most users should prefer the YAML format (see ``config/reports/*.yaml``)
because it requires zero Python. This file exists so power users have a
template for cases where they need dynamic logic (e.g. computing the card
list at runtime from a database query).
"""

from __future__ import annotations

from typing import Any, Sequence

from app.services.base import DomoBase


class ExamplePythonReport(DomoBase):
    """A bare-bones Python report. Mirrors the YAML structure 1:1."""

    name = "example_python_report"

    def file_name(self) -> str:
        return "example_python_report_metadata"

    def list_of_cards(self) -> Sequence[Sequence[Any]]:
        return [
            ["Example Dashboard", "Example Card", "Single Value"],
            ["Example Dashboard", "Example Trend", "Line"],
        ]

    def list_of_destinations(self) -> Sequence[dict]:
        return [
            {"type": "slack", "channel_name": "example-channel"},
        ]
