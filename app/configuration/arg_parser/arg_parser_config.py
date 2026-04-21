"""CLI argument parser.

Preserves the original ``--list <names>`` flag (for backward compatibility
with existing crontab wrappers) and adds:

    --all         Run every registered report once.
    --scheduler   Start the in-container APScheduler (blocks).
    --scaffold    Create a starter ``config/reports/<name>.yaml``.
    --validate    Parse all YAML reports without sending anything.
"""

from __future__ import annotations

import argparse


def configure_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domo-report",
        description="Send scheduled Domo card reports to Slack and Microsoft Teams.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--list",
        nargs="+",
        metavar="REPORT",
        help="Run the named registered report(s).",
    )
    mode.add_argument(
        "--all",
        action="store_true",
        help="Run every registered report once.",
    )
    mode.add_argument(
        "--scheduler",
        action="store_true",
        help="Start the in-container APScheduler (blocks).",
    )
    mode.add_argument(
        "--scaffold",
        action="store_true",
        help="Generate a starter config/reports/<name>.yaml stub.",
    )
    mode.add_argument(
        "--validate",
        action="store_true",
        help="Parse and validate every YAML report without sending anything.",
    )

    parser.add_argument(
        "--name",
        help="Report name to use with --scaffold (slugified for the filename).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="With --scaffold: overwrite an existing YAML file if present.",
    )

    return parser
