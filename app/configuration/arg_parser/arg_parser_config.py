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
    mode.add_argument(
        "--doctor",
        action="store_true",
        help="Run environment health checks (Python, engine creds, JAR, YAML, history).",
    )
    mode.add_argument(
        "--init",
        action="store_true",
        help="Interactive wizard to scaffold a new config/reports/<name>.yaml.",
    )
    mode.add_argument(
        "--list-engines",
        action="store_true",
        dest="list_engines",
        help="Print every registered Domo engine key and exit.",
    )
    mode.add_argument(
        "--list-destinations",
        action="store_true",
        dest="list_destinations",
        help="Print every registered destination type key and exit.",
    )
    mode.add_argument(
        "--download-jar",
        action="store_true",
        dest="download_jar",
        help=(
            "Download + verify the Domo CLI JAR (used by the jar engine). "
            "The SHA-256 pinned in app/engines/JAR_VERSION.json is enforced."
        ),
    )
    mode.add_argument(
        "--serve",
        action="store_true",
        dest="serve",
        help=(
            "Start the FastAPI + htmx web UI (requires the [web] extras). "
            "Use DOMO_WEB_HOST / DOMO_WEB_PORT to change the bind address."
        ),
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

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run the report end-to-end but don't actually send anything. "
            "Destinations log what they would have sent."
        ),
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help=(
            "Save every generated card image into state/preview/<report>/ "
            "so you can eyeball output locally. Can be combined with --dry-run."
        ),
    )
    parser.add_argument(
        "--preview-path",
        default="state/preview",
        help="Override the --preview output directory (default: state/preview).",
    )

    return parser
