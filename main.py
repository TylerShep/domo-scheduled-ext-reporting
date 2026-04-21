"""CLI entry point for domo-scheduled-ext-reporting."""

from __future__ import annotations

import sys

from app.configuration.arg_parser.arg_parser_config import configure_arg_parser
from app.configuration.report_loader import validate_all
from app.runtime import RuntimeFlags, set_flags
from app.service_manager.manager import ServiceManager
from app.utils.logger import configure_logging, get_logger
from app.utils.project_updates_util import scaffold_yaml_report

logger = get_logger(__name__)


def main() -> int:
    configure_logging()
    args = configure_arg_parser().parse_args()

    set_flags(
        RuntimeFlags(
            dry_run=bool(getattr(args, "dry_run", False)),
            preview=bool(getattr(args, "preview", False)),
            preview_path=getattr(args, "preview_path", "state/preview"),
        )
    )
    if args.dry_run:
        logger.warning("--dry-run enabled: nothing will actually be sent.")
    if args.preview:
        logger.warning(
            "--preview enabled: card images will be copied into %s",
            args.preview_path,
        )

    if args.scaffold:
        return _cmd_scaffold(args.name, args.overwrite)
    if args.validate:
        return _cmd_validate()
    if getattr(args, "doctor", False):
        return _cmd_doctor()
    if getattr(args, "init", False):
        return _cmd_init(args.name, args.overwrite)
    if getattr(args, "list_engines", False):
        return _cmd_list_engines()
    if getattr(args, "list_destinations", False):
        return _cmd_list_destinations()
    if getattr(args, "download_jar", False):
        return _cmd_download_jar()
    if getattr(args, "serve", False):
        return _cmd_serve()
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


def _cmd_doctor() -> int:
    from app.cli.doctor import print_report, run_doctor

    report = run_doctor()
    print_report(report)
    return report.exit_code


def _cmd_init(name: str | None, overwrite: bool) -> int:
    from app.cli.init_wizard import InitWizardError, run_init_wizard

    answers = {"name": name} if name else None
    try:
        path = run_init_wizard(answers=answers, overwrite=overwrite)
    except InitWizardError as exc:
        logger.error("init wizard failed: %s", exc)
        return 1
    logger.info("Created %s", path)
    return 0


def _cmd_list_engines() -> int:
    from app.cli.listing import list_engines, print_with_labels

    return print_with_labels(list_engines(), "engines")


def _cmd_list_destinations() -> int:
    from app.cli.listing import list_destinations, print_with_labels

    return print_with_labels(list_destinations(), "destinations")


def _cmd_serve() -> int:
    try:
        import uvicorn
    except ImportError:
        logger.error(
            "The [web] extras are not installed. Run "
            "`pip install 'domo-scheduled-ext-reporting[web]'`."
        )
        return 1
    from app.web import create_app
    from app.web.config import WebConfig

    cfg = WebConfig.from_env()
    app = create_app(cfg)
    logger.info("Web UI starting on http://%s:%d", cfg.bind_host, cfg.bind_port)
    uvicorn.run(app, host=cfg.bind_host, port=cfg.bind_port, log_level="info")
    return 0


def _cmd_download_jar() -> int:
    from app.engines.jar_downloader import (
        JarDownloadError,
        default_install_path,
        describe_version,
        download_jar,
    )

    logger.info("Target install path: %s", default_install_path())
    logger.info("Pinned JAR version: %s", describe_version())
    try:
        path = download_jar()
    except JarDownloadError as exc:
        logger.error("JAR download failed: %s", exc)
        return 1
    logger.info("Installed JAR: %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
