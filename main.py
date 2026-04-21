"""CLI entry point for domo-scheduled-ext-reporting."""

from __future__ import annotations

import sys

from app.configuration.arg_parser.arg_parser_config import configure_arg_parser
from app.configuration.report_loader import validate_all
from app.service_manager.manager import ServiceManager
from app.utils.logger import configure_logging, get_logger
from app.utils.project_updates_util import scaffold_yaml_report

logger = get_logger(__name__)


def main() -> int:
    configure_logging()
    args = configure_arg_parser().parse_args()

    if args.scaffold:
        return _cmd_scaffold(args.name, args.overwrite)
    if args.validate:
        return _cmd_validate()
    if args.scheduler:
        return _cmd_scheduler()
    if args.all:
        return _cmd_all()
    if args.list:
        return _cmd_list(args.list)
    return 0


def _cmd_scaffold(name: str | None, overwrite: bool) -> int:
    if not name:
        logger.error("--scaffold requires --name <report_name>")
        return 2
    try:
        path = scaffold_yaml_report(name, overwrite=overwrite)
    except FileExistsError as exc:
        logger.error("%s. Pass --overwrite to replace.", exc)
        return 1
    logger.info("Created %s", path)
    return 0


def _cmd_validate() -> int:
    valid, errors = validate_all()
    for spec in valid:
        logger.info(
            "OK  %-30s -> %d card(s), %d destination(s), schedule=%s",
            spec.name,
            len(spec.cards),
            len(spec.destinations),
            spec.schedule or "<none>",
        )
    for err in errors:
        logger.error("ERR %s", err)
    return 0 if not errors else 1


def _cmd_scheduler() -> int:
    from app.scheduler.runner import run_forever

    run_forever()
    return 0


def _cmd_all() -> int:
    ServiceManager.execute_all()
    return 0


def _cmd_list(names: list[str]) -> int:
    exit_code = 0
    for name in names:
        try:
            ServiceManager.execute(name)
        except Exception:
            logger.exception("Report %s failed", name)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
