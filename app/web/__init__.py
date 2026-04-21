"""Optional FastAPI + htmx + Alpine.js web UI.

Importing this module requires the ``[web]`` extra to be installed::

    pip install "domo-scheduled-ext-reporting[web]"

The public entry points are :func:`create_app` (for ASGI) and the CLI
``--serve`` flag which boots uvicorn programmatically.
"""

from __future__ import annotations

from app.web.app import create_app

__all__ = ["create_app"]
