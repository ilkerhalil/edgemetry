# Contributing

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Before opening a pull request

```bash
.venv/bin/ruff check .
.venv/bin/ruff format .
.venv/bin/python -m pytest -q
```

Integration tests that need a database are skipped unless `EDGEMETRY_TEST_DSN` is set:

```bash
EDGEMETRY_TEST_DSN="postgresql://postgres:edgemetry@localhost:5432/edgemetry" \
  .venv/bin/python -m pytest tests/integration -q
```

## Rules

- **A behaviour change needs a test.** Bug fixes start with a failing test that reproduces the bug.
- **No dependency without a reason.** The receiver is stdlib-only by design; optional extras carry
  their own import guard so a minimal install still works.
- **Units in names.** Durations are `_ns` unless the function explicitly converts for display.
- **Do not compute what the database can compute.** If a backend can aggregate in place, the query
  belongs there, not in a Python loop over rows.
- Commit messages follow `type: subject` — `feat`, `fix`, `docs`, `test`, `refactor`, `chore`.

## Layout

```
src/edgemetry/      package
tests/unit/        no I/O beyond a temporary SQLite file
tests/integration/ real HTTP server, real database
docs/              architecture, API, deployment
deploy/            collector configuration
demo/              traffic generators and the scale check
```
