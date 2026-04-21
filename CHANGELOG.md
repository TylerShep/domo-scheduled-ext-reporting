# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2026-04-21

Major rebuild that ships across 15 commits. Highlights: a native REST client (no JVM required), persistent run history, an opt-in web UI, a dataset/file delivery pipeline, an SMTP destination, a sandboxed `send_when:` alert engine, Jinja-templated copy throughout, full `doctor` / `init` CLI helpers, a 56MB JAR moved out of the repo, and a 432-test suite at 85.6% coverage.

See [`docs/migration_v1_to_v2.md`](docs/migration_v1_to_v2.md) for the upgrade path and breaking changes.

### Added

- **REST engine** (`app/engines/rest.py`) -- native Python client against `public.domo.com`. Default `DOMO_ENGINE=rest`, no JVM required.
- **Pluggable engine layer** (`app/engines/{base,jar,registry}.py`) -- `JarEngine` and `RestEngine` are interchangeable; new engines can register via `engine_factory(...)`.
- **JAR downloader** (`app/engines/jar_downloader.py`) -- fetches `domoUtil.jar` from GitHub Releases on demand with SHA-256 verification. New CLI flag `--download-jar`.
- **Run history** (`app/history/`) -- `HistoryBackend` ABC + SQLite (default), Postgres, Null implementations. Captures per-card and per-destination outcomes, including `send_when` skips. Configurable via `RUN_HISTORY_BACKEND`.
- **Prometheus metrics** (`app/observability/metrics.py`) -- counters for runs, cards, sends, skips, failures. Exposed at `/metrics`. Degrades to no-ops when the `[metrics]` extra is not installed.
- **Datasets pipeline** -- new `datasets:` key in YAML reports plus `app/destinations/file.py` that delivers CSV/XLSX to local folders, Slack, Teams (Graph), or email.
- **Email destination** (`app/destinations/email.py`) -- SMTP with multipart, inline images via Content-IDs, optional dataset attachments, Markdown rendering, Jinja-templated subject + body.
- **Sandboxed `send_when:` alerts** (`app/alerts/`) -- gate cards, datasets, and individual destinations on `asteval` expressions evaluated in `minimal` mode against a curated context (`card`, `dataset`, `run`, `env`).
- **Card auto-discovery** (`app/configuration/card_resolver.py`) -- new `cards_query:` YAML key resolves cards from page / tag filters via `engine.list_cards()` with a TTL cache at `app/state/discovery_cache.json`.
- **Jinja templating engine** (`app/templating/engine.py`) -- `StrictUndefined` rendering with `currency`, `pct`, `delta`, `human_number` filters. Plumbed through Slack `initial_comment`, Teams chatMessage HTML, Email subject/body, and per-card captions.
- **Slack threading + reactions + scheduled sends** -- `thread:` (literal `ts` or `"first_card"`), `react_on_send: [emoji]`, `schedule_at:` (Unix ts or ISO 8601).
- **Teams polish** -- Graph mode supports `single_carousel` (one chatMessage with all card attachments + summary + AAD mentions); webhook mode supports the legacy `MessageCard` payload with sections and facts.
- **Conditional + dry-run + preview modes** -- new `--dry-run` and `--preview` CLI flags plus per-destination `dry_run:` toggles. Preview mode writes a copy of every generated PNG to `app/state/preview/`.
- **`--doctor` health checks** (`app/cli/doctor.py`) -- environment, engine, JAR, history, destinations, optional deps. `rich`-formatted output when installed, plain text otherwise.
- **`--init` interactive wizard** (`app/cli/init_wizard.py`) -- scaffolds a YAML report from prompts. Replaces the old `--scaffold` flag.
- **`--list-engines` / `--list-destinations`** -- inspect the registry from the CLI.
- **Web UI** (`app/web/`, FastAPI + htmx + Alpine.js) -- argon2 auth, signed session cookies, CSRF tokens, full CRUD over `config/reports/` (round-trip-edited via `ruamel.yaml`), run history view, per-destination dry-run test endpoint, `/healthz`, `/metrics`. New CLI flag `--serve`. Configured via `DOMO_WEB_*` env vars.
- **Test infrastructure** -- `tests/factories.py`, `tests/e2e/`, property tests via `hypothesis`, mocked HTTP via `responses`, deterministic clocks via `freezegun`. 432 tests at 85.6% line+branch coverage.
- **CI matrix** -- runs on Python 3.10/3.11/3.12 in two extras combinations (`dev` and `dev,web,metrics`), uploads `coverage.xml`, builds the Docker image with and without the JAR, and smokes the CLI.

### Changed

- **Default Domo client is REST.** Set `DOMO_ENGINE=jar` to keep using the legacy CLI.
- **`DomoBase` no longer takes a JAR path.** It resolves the active engine via `app.engines.get_engine()`. Existing Python subclasses keep working as long as they don't pass JAR paths around.
- **YAML schema** -- a report must now define at least one of `cards:`, `cards_query:`, or `datasets:`. Empty `cards: []` is no longer silently accepted.
- **Coverage gate** -- raised from "report only" to a hard `--cov-fail-under=85`.
- **Image cropping** -- now uses `Image.LANCZOS` for higher-quality resizing.
- **`app.utils.domo_util` is now a backward-compat shim** that delegates to `JarEngine` -- old call sites keep working unchanged.

### Removed

- **`app/utils/domoUtil.jar` is no longer in the repo.** Use `domo-report --download-jar` (or build with `--build-arg INSTALL_JRE=true`) to install it.
- **`--scaffold` CLI flag** -- replaced by `--init`.
- **Python 3.9 support** -- minimum version is now 3.10.

### Deprecated

- The `app.utils.domo_util` module is kept for one major release as a compatibility shim. New code should import `app.engines.get_engine()` directly.

## [1.0.0] - 2026-04-21

Initial public release. Rebuilt from a private RentDynamics-internal prototype (`domo-slack-reporting`) for the broader Domo community.

### Added

- **Microsoft Teams** support as a first-class destination, with both Graph API (full file uploads) and Incoming Webhook (Adaptive Card with base64 image) modes
- **YAML-driven reports** -- add a new scheduled report by dropping a file in `config/reports/`. No Python required.
- **Pluggable destination layer** (`app/destinations/`) -- Slack and Teams ship by default; new destinations register via a registry factory
- **Per-report fan-out** -- a single report can target many Slack channels and many Teams channels in one run
- **Built-in APScheduler** runner (`python main.py --scheduler`)
- **Example GitHub Actions workflow** for serverless scheduling
- New CLI flags: `--all`, `--scheduler`, `--scaffold`, `--validate`
- **Image post-processing presets** for `Bar`, `Stacked Bar`, `Horizontal Bar`, `Pie`, `Donut`, `Heatmap`, `Map`, `Table`, `Gauge`, `Area`, `Scatter`
- Per-card YAML overrides for `crop`, `resize`, `add_caption`, `caption_text`
- RGBA-to-RGB flattening so card transparencies render cleanly in Teams
- Comprehensive `pytest` suite (~60 tests)
- Structured logging with optional rotating log files
- Retry/backoff on Domo CLI and Teams API failures via `tenacity`
- Comprehensive `README.md` with setup guides, troubleshooting matrix, and architecture diagrams
- `CONTRIBUTING.md`, `CHANGELOG.md`, and a CI workflow

### Changed

- **Batched JVM execution** -- the original spawned one JVM per card (~9 cold starts for a typical 9-card report). Now a single JVM serves the entire report (~5x faster on a 9-card report).
- Replaced `boto3` / AWS Secrets Manager with vendor-neutral `python-dotenv`
- Replaced CircleCI with GitHub Actions
- Replaced `unittest` with `pytest`
- Renamed `DJANGO_CONFIGURATION` env var to `APP_ENV` (this isn't a Django app)
- Renamed `DomoSlackBase` to `DomoBase` (it's no longer Slack-specific)
- Better error messages -- e.g. metadata-CSV column-mismatch failures now tell you exactly which columns are missing

### Removed

- All RD/Entrata-specific report definitions (`twilio_daily_spend`, `rp_daily_numbers`, `pm_sync_analysis`, `rd_rp_support`, `hb_da_daily_numbers`)
- `app/aws/` (Secrets Manager + S3 helpers)
- `deploy/` directory (supervisord, Datadog agent config, AWS security group scripts, CircleCI deploy handler)
- `.circleci/`, `docker/docker-compose.circleci.yaml`, `CODEOWNERS`
- Unused Python deps: `boto3`, `botocore`, `boto`, `bcrypt`, `Cython`, `matplotlib`, `numpy` (and a long tail of transitive cruft)
