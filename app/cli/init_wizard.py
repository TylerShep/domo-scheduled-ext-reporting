"""`domo-report --init` -- interactive wizard to scaffold a new report.

Walks the user through a minimal set of prompts and writes a YAML file
under ``config/reports/<slug>.yaml``.  Not meant to be exhaustive --
we cover the common case (one card, one destination) and let the user
hand-edit afterwards.

For test/automation, the wizard accepts an ``answers`` dict that skips
the prompt loop entirely.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from app.utils.logger import get_logger
from app.utils.project_setup_util import clean_filename

logger = get_logger(__name__)


_DEFAULT_REPORTS_DIR = Path("config/reports")


class InitWizardError(RuntimeError):
    """Raised on invalid / missing wizard input."""


def _default_prompter(prompt: str, default: str | None = None) -> str:
    """Readline-style prompt helper.  Overridden in tests."""

    hint = f" [{default}]" if default else ""
    answer = input(f"{prompt}{hint}: ").strip()
    return answer or (default or "")


def run_init_wizard(
    answers: dict[str, Any] | None = None,
    prompter: Callable[[str, str | None], str] | None = None,
    output_dir: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Build a new report YAML and return its path.

    Args:
        answers: Pre-canned answers keyed by prompt id (``name``, ``page``,
            ``card``, ``viz_type``, ``destination_type``, ``channel_name``,
            etc.).  When provided we skip the prompt loop entirely.
        prompter: Function that accepts ``(prompt, default)`` and returns
            the user's answer.  Overridden in tests.
        output_dir: Override the output directory (default
            ``config/reports``).
        overwrite: If False (the default), raise when the file exists.
    """

    ask = prompter or _default_prompter
    answers = dict(answers or {})

    def _get(key: str, prompt: str, default: str | None = None) -> str:
        if key in answers:
            return str(answers[key])
        return ask(prompt, default)

    report_name = _get("name", "Report name", default="Daily Revenue")
    if not report_name:
        raise InitWizardError("report name is required")

    metadata_ds = _get(
        "metadata_dataset_file_name",
        "Metadata dataset filename (no extension)",
        default=clean_filename(report_name),
    )

    page = _get("page", "Domo page (dashboard) name", default="Sales")
    card = _get("card", "Domo card name", default="Revenue")
    viz = _get("viz_type", "Viz type", default="Bar Chart")

    dest_type = _get(
        "destination_type",
        "Destination type (slack | teams | email | file)",
        default="slack",
    ).lower()

    spec: dict[str, Any] = {
        "name": report_name,
        "metadata_dataset_file_name": metadata_ds,
        "cards": [
            {
                "dashboard": page,
                "card": card,
                "viz_type": viz,
            }
        ],
        "destinations": [_build_destination_block(dest_type, answers, ask)],
    }

    base = output_dir or _DEFAULT_REPORTS_DIR
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"{clean_filename(report_name)}.yaml"

    if target.exists() and not overwrite:
        raise InitWizardError(f"{target} already exists. Pass overwrite=True (or delete the file).")

    target.write_text(yaml.safe_dump(spec, sort_keys=False))
    logger.info("Created %s", target)
    return target


def _build_destination_block(
    dest_type: str,
    answers: dict[str, Any],
    ask: Callable[[str, str | None], str],
) -> dict[str, Any]:
    """Return a ready-to-serialize destination dict for ``dest_type``."""

    block: dict[str, Any] = {"type": dest_type}

    def _a(key: str, prompt: str, default: str | None = None) -> str:
        if key in answers:
            return str(answers[key])
        return ask(prompt, default)

    if dest_type == "slack":
        block["channel_name"] = _a("channel_name", "Slack channel name (no #)", "data-drops")
    elif dest_type == "teams":
        auth_mode = _a("auth_mode", "Teams auth mode (graph | webhook)", "webhook")
        block["auth_mode"] = auth_mode
        if auth_mode == "graph":
            block["team_id"] = _a("team_id", "Team ID")
            block["channel_id"] = _a("channel_id", "Channel ID")
        else:
            block["webhook_url_env"] = _a(
                "webhook_url_env",
                "Env var holding the webhook URL",
                "TEAMS_WEBHOOK_URL",
            )
    elif dest_type == "email":
        block["to"] = _split_list(_a("to", "Recipient email(s) (comma-separated)"))
        block["subject_template"] = _a(
            "subject_template",
            "Subject template",
            "{{ report_name }} -- {{ today }}",
        )
    elif dest_type == "file":
        block["target"] = _a(
            "file_target", "File target (local | slack | teams_graph | email)", "local"
        )
    else:
        raise InitWizardError(f"Unsupported destination type: {dest_type}")

    return block


def _split_list(s: str) -> list[str]:
    return [part.strip() for part in s.split(",") if part.strip()]
