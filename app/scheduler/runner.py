"""Long-running APScheduler that fires registered reports on cron schedules.

Each report's schedule is sourced from (in priority order):

    1. ``config/schedule.yaml`` (a global override; map of report name -> cron string)
    2. The report's own YAML file ``schedule:`` field
    3. Skipped if neither is set.

Run with ``python main.py --scheduler``. The process blocks forever; ship
this in a long-lived container or systemd unit.
"""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.configuration.report_loader import (
    ReportSpec,
    discover_yaml_files,
    parse_report_file,
)
from app.service_manager.manager import ServiceManager
from app.utils.logger import get_logger

logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_SCHEDULE_OVERRIDE_FILE = _REPO_ROOT / "config" / "schedule.yaml"


def _load_schedule_overrides() -> dict[str, str]:
    """Load ``config/schedule.yaml`` if present; otherwise return ``{}``."""

    if not _SCHEDULE_OVERRIDE_FILE.exists():
        return {}
    with _SCHEDULE_OVERRIDE_FILE.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        logger.warning("%s root must be a mapping; ignoring.", _SCHEDULE_OVERRIDE_FILE)
        return {}
    return {str(k): str(v) for k, v in data.items() if v}


def _gather_yaml_specs() -> list[ReportSpec]:
    out: list[ReportSpec] = []
    for path in discover_yaml_files():
        try:
            out.append(parse_report_file(path))
        except Exception:
            logger.exception("Skipping invalid YAML report %s", path)
    return out


def _run_report_safely(report_name: str) -> None:
    """Wrapper around :meth:`ServiceManager.execute` for the scheduler."""

    logger.info("Triggering scheduled report: %s", report_name)
    try:
        ServiceManager.execute(report_name)
    except Exception:
        logger.exception("Scheduled report %s failed", report_name)


def build_scheduler() -> BlockingScheduler:
    """Construct (but don't start) the APScheduler with all jobs added."""

    scheduler = BlockingScheduler(timezone="UTC")
    overrides = _load_schedule_overrides()

    yaml_specs = {spec.name: spec for spec in _gather_yaml_specs()}
    registered_names = set(ServiceManager.get_sync_names())

    scheduled_count = 0
    for name in registered_names:
        cron = overrides.get(name) or _schedule_from_spec(yaml_specs.get(name))
        if not cron:
            logger.info("Report %s has no schedule; skipping.", name)
            continue
        try:
            trigger = CronTrigger.from_crontab(cron, timezone="UTC")
        except Exception as exc:
            logger.error("Bad cron expression %r for %s: %s", cron, name, exc)
            continue

        scheduler.add_job(
            _run_report_safely,
            trigger=trigger,
            args=[name],
            id=name,
            name=name,
            replace_existing=True,
            misfire_grace_time=300,
        )
        scheduled_count += 1
        logger.info("Scheduled %s at cron=%r (UTC)", name, cron)

    if scheduled_count == 0:
        logger.warning(
            "No reports were scheduled. Add `schedule:` to a report YAML or "
            "create config/schedule.yaml."
        )
    return scheduler


def _schedule_from_spec(spec: ReportSpec | None) -> str | None:
    if spec is None:
        return None
    return spec.schedule


def run_forever() -> None:
    """Build the scheduler and block until SIGINT/SIGTERM."""

    scheduler = build_scheduler()

    def _shutdown(signum: int, _frame: Any) -> None:
        logger.info("Received signal %s; shutting scheduler down.", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    logger.info("Scheduler starting (Ctrl+C to stop)...")
    scheduler.start()
