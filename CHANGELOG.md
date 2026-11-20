# Changelog

All notable changes are recorded here. Format follows Keep a Changelog; versions follow SemVer.

## [0.2.0] — 2026-11-20

### Added

- OTLP/protobuf ingest via the official generated classes; the decoder is chosen by `Content-Type`.
- PostgreSQL backend with `percentile_cont` aggregation, selected by `--backend postgres`.
- `spanlens verify` — reports the share of client spans that carry a callee identifier and exits `2`
  when a service is below 95 % coverage.
- `deploy/otel-collector-dynatrace.yaml` — dual export to Dynatrace and SpanLens.
- Documentation set under `docs/`: architecture, HTTP API, deployment.

### Changed

- `serve` takes a store instance instead of a database path; `make_server` allows port 0 in tests.
- PostgreSQL ingest uses `COPY`: 100 000 spans dropped from 9.11 s to 1.98 s.

## [0.1.0] — 2026-11-20

### Added

- OTLP/JSON receiver, SQLite store, latency aggregation per caller/callee/operation.
- Trace waterfall endpoint with computed self time.
- Demo emitter with known latency distribution.
