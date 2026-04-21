"""`--list-engines` / `--list-destinations` helpers.

Tiny commands that introspect the registries and print what's wired up so
new users can discover the extension points without reading the source.
"""

from __future__ import annotations

from collections.abc import Iterable


def list_engines() -> list[str]:
    """Return every registered engine key (``rest``, ``jar``, ``auto``)."""

    from app.engines.registry import available_engines

    return available_engines()


def list_destinations() -> list[str]:
    """Return every registered destination key (``slack``, ``teams``, ...)."""

    from app.destinations.registry import known_destination_types

    return known_destination_types()


def print_engines(stream_write=print) -> int:
    for key in list_engines():
        stream_write(key)
    return 0


def print_destinations(stream_write=print) -> int:
    for key in list_destinations():
        stream_write(key)
    return 0


def print_with_labels(items: Iterable[str], kind: str) -> int:
    """Pretty-print with a small rich table when available."""

    try:
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title=f"Registered {kind}")
        table.add_column(kind.rstrip("s").capitalize())
        for item in items:
            table.add_row(item)
        console.print(table)
    except ImportError:
        for item in items:
            print(item)
    return 0
