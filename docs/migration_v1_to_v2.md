# Migrating from v1 to v2

v2 is a structural upgrade: the JAR is no longer the only Domo client, run history is persisted, the YAML schema gained `datasets:` / `cards_query:` / `send_when:`, and there's a web UI. **Existing v1 reports keep working** -- the changes below are opt-in unless flagged as **Breaking**.

If you only ever used Slack + a couple of reports, the migration is essentially:

```bash
pip install -e ".[dev,web,metrics]"
domo-report --doctor      # confirm env
# ... run as before
```

The detailed checklist follows.

## Quick checklist

- [ ] **Python 3.10+** -- v1 supported 3.9; v2 drops it (the codebase uses 3.10 generics: `list[str]` etc.).
- [ ] **Move the JAR.** It's no longer in-repo. Either let `domo-report --download-jar` fetch it from GitHub Releases, or symlink your existing copy at `app/utils/domoUtil.jar`.
- [ ] **(Optional) Switch to `DOMO_ENGINE=rest`.** No JVM, faster cold starts, fewer install steps.
- [ ] **(Optional) Pick a history backend.** SQLite ships by default; set `RUN_HISTORY_BACKEND=null` to keep v1 behavior.
- [ ] **(Optional) Stand up the web UI** with `domo-report --serve` and the `[web]` extras.

## Breaking changes

### 1. Bundled JAR is no longer in the repo

v1 shipped `app/utils/domoUtil.jar` directly. v2 keeps the binary out of git (it was 56 MB) and downloads on demand.

**Fix:** run `domo-report --download-jar` once. The downloader verifies SHA-256 against `app/engines/JAR_VERSION.json` and installs to `app/utils/domoUtil.jar`. In Docker, set `--build-arg INSTALL_JRE=true` and the build downloads the JAR for you.

### 2. Default Domo client is REST, not the CLI JAR

The default `DOMO_ENGINE` is now `rest`. If your environment relies on JAR-only behavior (e.g. local network restrictions on `public.domo.com`), set:

```bash
DOMO_ENGINE=jar
```

Both engines implement the same interface, so YAML reports don't change.

### 3. `app/services/base.py` constructor takes no engine

In v1, `DomoBase` took the JAR path as a constructor argument. v2 resolves the active engine via `app.engines.get_engine()`. If you subclassed `DomoBase` in your private code, drop the JAR-path argument and stop calling `domo_util.exec_*` directly -- use `engine.export_dataset(...)` and `engine.generate_card_images(...)`.

The legacy `app.utils.domo_util` functions (`exec_domo_util_batch`, `exec_domo_generate_image`, etc.) are kept as thin shims for backwards compatibility, but they always go through the JAR engine.

### 4. `RunStatus` enum and `RunRecord` model

If you ever reached into history files, the on-disk schema (SQLite at `app/state/run_history.db`) gained `skipped`, `skip_reason`, and `cards_skipped` columns. The migration runs automatically on boot (`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`), so existing DBs keep working with no manual step.

### 5. `--scaffold` is now `--init` (interactive wizard)

The old `--scaffold` flag is gone. Run:

```bash
domo-report --init
```

You'll be prompted through report name, cards, and destinations.

### 6. Tightened YAML validator

A report with no `cards:`, `cards_query:`, or `datasets:` is now an error. v1 accepted empty `cards: []` lists silently.

## New optional features

These don't break anything, but they're worth turning on:

### REST engine (default)

```bash
DOMO_ENGINE=rest
DOMO_CLIENT_ID=...
DOMO_CLIENT_SECRET=...
```

### Run history

```bash
# Default; writes to app/state/run_history.db
RUN_HISTORY_BACKEND=sqlite

# Postgres alternative
RUN_HISTORY_BACKEND=postgres
DATABASE_URL=postgresql://user:pass@host/db
```

`domo-report --serve` then exposes a `/runs` page, and `/metrics` (if `[metrics]` is installed) speaks Prometheus.

### Datasets

```yaml
datasets:
  - name: daily_rollup
    dataset_id: abc-123-def
    format: csv     # or xlsx
```

Pair with a `file` destination to drop CSV/XLSX into a folder, Slack, Teams, or email.

### Auto-discover cards

```yaml
cards_query:
  page: "Sales"
  tags: ["daily"]
  exclude_tags: ["wip"]
```

Caches at `app/state/discovery_cache.json` for `DISCOVERY_CACHE_TTL_SECONDS` seconds.

### Conditional sending

```yaml
cards:
  - dashboard: Sales
    card: Daily Revenue
    viz_type: Single Value
    send_when: "card.summary_value | float > 10000"
```

Sandboxed via `asteval` -- no `os.system`, no imports, no dunder access.

### Email + dry-run

```yaml
destinations:
  - type: email
    to: ["analytics@example.com"]
    subject: "Sales {{ today }}"
    dry_run: true   # build the message but don't actually SMTP-send
```

Combine with `--preview` and a copy of every generated PNG lands in `app/state/preview/` for inspection.

### Web UI

```bash
pip install -e ".[web]"
domo-report --serve --bind-host 127.0.0.1 --bind-port 8080
# DOMO_WEB_ADMIN_USER=admin
# DOMO_WEB_ADMIN_PASSWORD_HASH=$(python -c "from app.web.auth import hash_password; print(hash_password('changeme'))")
```

Full CRUD over `config/reports/`, with run history view and per-destination dry-run tests.

## Validation

After the migration:

```bash
domo-report --doctor          # green checkmarks across the board
domo-report --list daily_kpis # smoke-test one report
pytest --cov=app              # 432 tests, ~85% coverage
```

If `domo-report --doctor` flags anything, the messages tell you exactly which env var or extras are missing.
