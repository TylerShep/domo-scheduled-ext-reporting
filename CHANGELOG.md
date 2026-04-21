# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
