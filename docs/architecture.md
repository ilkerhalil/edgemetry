# Architecture

SpanLens is a span store with a narrow purpose: keep the attributes that identify a callee, and
aggregate latency over them. Everything else — alerting, topology, service health — belongs to the
APM that is already deployed.

## Data flow

```
application
   │  OTLP gRPC/HTTP
   ▼
OpenTelemetry Collector
   ├── otlphttp/dynatrace   → existing APM, unchanged
   └── otlphttp/spanlens    → SpanLens receiver
                                   │
                        ┌──────────┴──────────┐
                        │  decode (proto/json)│
                        │  normalise peer     │
                        │  store              │
                        └──────────┬──────────┘
                                   ▼
                          SQLite  |  PostgreSQL
                                   │
                            query API / CLI
```

The collector does the fan-out. SpanLens never sits in the request path: if it is down, applications
and the APM are unaffected, and the collector's own queue absorbs the gap.

## Module map

| Module | Responsibility |
|---|---|
| `model.py` | `Span` value object, OTLP/JSON decoding, peer extraction, waterfall building |
| `otlp_proto.py` | OTLP/protobuf decoding using the official generated classes |
| `store.py` | SQLite backend, percentile arithmetic, edge aggregation |
| `store_pg.py` | PostgreSQL backend; percentiles computed with `percentile_cont` |
| `api.py` | HTTP receiver and query endpoints, stdlib only |
| `cli.py` | `serve`, `query`, `verify`, `trace` |

Both stores expose the same four methods — `insert`, `edges`, `trace`, `peer_coverage` — plus
`close`. That interface is the seam: a ClickHouse backend only has to implement it.

## Key decisions

**Nanoseconds everywhere.** OTLP transmits `startTimeUnixNano` and `endTimeUnixNano` as decimal
strings. They are parsed to integers once, stored as integers, and divided by 1e6 only when a
human-readable number is printed. Mixing microseconds and nanoseconds is the classic way to report a
number that is wrong by 1000×; the unit lives in the column name, not in a comment.

**Self time is derived, never stored.** A flat span list cannot answer "where did the time go". The
waterfall builder subtracts the sum of direct children from the parent duration and clamps at zero,
because clock skew across hosts can make children appear longer than their parent.

**Percentiles are computed where the data is.** SQLite pulls durations into the process and applies
nearest-rank interpolation; PostgreSQL uses `percentile_cont`. That difference is the reason the
Postgres backend exists.

**Ingest decodes by content type.** `application/x-protobuf` goes through the generated OTLP classes;
anything else is treated as OTLP/JSON. A missing optional dependency answers `415` with the install
hint instead of failing at import time, so a JSON-only deployment stays dependency-free.

**No authentication in v0.1.** The receiver assumes a trusted network segment next to the collector.
Putting a token check in front of it is a deployment concern, not a code path to invent badly.

## What is deliberately missing

- Rollups and retention. Every query scans its window; at high volume that is the first thing to fix.
- Sampling awareness. If the collector samples, counts are a sample of requests, not request totals.
- Trace-level indexing beyond `trace_id`. Deep search across attributes is not a v0.1 feature.
