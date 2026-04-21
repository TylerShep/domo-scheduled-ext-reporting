"""Pytest configuration shared by every test module."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow `import app...` and `import main` from tests without packaging.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    """Reset the ServiceManager registry between every test session."""

    from app.service_manager.manager import ServiceManager

    ServiceManager.reset()
