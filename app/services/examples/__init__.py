"""Optional Python-subclass report examples.

Reports defined as Python subclasses must register themselves here so the
:class:`~app.service_manager.manager.ServiceManager` picks them up. This
file ships with one toy report that you can delete once you have your own.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.examples.example_python_report import ExamplePythonReport

if TYPE_CHECKING:
    from app.service_manager.manager import ServiceManager


def register_examples(manager: type[ServiceManager]) -> None:
    """Called by ``ServiceManager._ensure_initialized`` at boot."""

    # Comment out (or delete this file's contents) if you don't want the
    # example showing up in `python main.py --list`.
    manager.register_many([ExamplePythonReport()])


__all__ = ["ExamplePythonReport", "register_examples"]
