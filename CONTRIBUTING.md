# Contributing

Thanks for your interest in contributing! This project is an open-source community resource for the Domo ecosystem -- bug reports, docs improvements, and PRs are all welcome.

## Quick links

- Bugs / feature requests: [GitHub Issues](https://github.com/TylerShep/domo-scheduled-ext-reporting/issues)
- Pull requests: target `main`, keep them focused

## Development setup

```bash
git clone https://github.com/TylerShep/domo-scheduled-ext-reporting.git
cd domo-scheduled-ext-reporting
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

Or via Docker:

```bash
make up
make shell
```

## Running tests

```bash
pytest                 # full suite
pytest -k slack        # subset
pytest --cov=app       # with coverage
```

The CI workflow runs the same suite plus `ruff check` and `black --check` on every PR.

## Code style

- `black` formatting (line length 100)
- `ruff` linting (config in `pyproject.toml`)
- Type hints on all new public functions
- Add a docstring to anything non-trivial
- Tests required for new behavior

Run the formatter / linter before pushing:

```bash
black app tests main.py
ruff check app tests --fix
```

## Adding a new destination type

1. Create `app/destinations/your_destination.py` subclassing `Destination`
2. Implement `prepare()` (one-time setup) and `send_image(ctx)`
3. Register the factory in `app/destinations/registry.py`
4. Add tests in `tests/test_destinations_<name>.py`
5. Document it in `README.md`

## Adding a new image preset

Edit `PRESETS` in [`app/utils/image_util.py`](app/utils/image_util.py). Add a `tests/test_image_util.py` case.

## Reporting bugs

Please include:

- Python version (`python --version`)
- OS (incl. whether you're inside Docker)
- The full error / stack trace
- A minimal YAML report that reproduces the issue (with names redacted as needed)

## Conventional commits (preferred, not required)

`feat: add Heatmap viz preset`, `fix: handle empty cards list`, `docs: update Teams setup guide`, etc.

## License

By contributing, you agree your contributions will be licensed under the [MIT License](LICENSE).
