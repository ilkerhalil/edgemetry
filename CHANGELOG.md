# Changelog

All notable changes are recorded here. Format follows Keep a Changelog; versions follow SemVer.

## [0.3.0] — 2026-11-20

### Changed

- **Renamed to Edgemetry.** The `spanlens` name on PyPI belongs to an unrelated project, so the
  distribution, import package and CLI are now `edgemetry`. The GitHub repository was renamed too.

### Added

- Bearer-token authentication on ingest and queries (`--token` / `$EDGEMETRY_TOKEN`); `/health` stays
  public. The startup line reports `auth=bearer token` or `auth=NO AUTH`.
- Retention: `--retention 7d` prunes at start and every six hours, plus `edgemetry prune
  --older-than 7d [--dry-run]`.
- `/health` now queries the store and returns `503 {"status":"degraded"}` when it is down.
- Store failures return `503` instead of dropping the connection.
- `edgemetry query --format json` for scripting.

## [0.2.0] — 2026-11-20

### Added

- OTLP/protobuf ingest via the official generated classes; the decoder is chosen by `Content-Type`.
- PostgreSQL backend with `percentile_cont` aggregation, selected by `--backend postgres`.
- `edgemetry verify` — reports the share of client spans that carry a callee identifier and exits `2`
  when a service is below 95 % coverage.
- `deploy/otel-collector-dynatrace.yaml` — dual export to Dynatrace and Edgemetry.
- Documentation set under `docs/`: architecture, HTTP API, deployment.

### Changed

- `serve` takes a store instance instead of a database path; `make_server` allows port 0 in tests.
- PostgreSQL ingest uses `COPY`: 100 000 spans dropped from 9.11 s to 1.98 s.

## [0.1.0] — 2026-11-20

### Added

- OTLP/JSON receiver, SQLite store, latency aggregation per caller/callee/operation.
- Trace waterfall endpoint with computed self time.
- Demo emitter with known latency distribution.
