"""Command-line helper subcommands.

This sub-package powers the ``--doctor``, ``--init``, ``--list-engines``,
and ``--list-destinations`` CLI flags (see :mod:`main`).  The goal is to
give new users a quick way to confirm their environment is wired up
correctly before scheduling any reports.
"""

from __future__ import annotations

from app.cli.doctor import DoctorCheck, DoctorReport, run_doctor
from app.cli.init_wizard import run_init_wizard
from app.cli.listing import list_destinations, list_engines

__all__ = [
    "DoctorCheck",
    "DoctorReport",
    "run_doctor",
    "run_init_wizard",
    "list_destinations",
    "list_engines",
]
