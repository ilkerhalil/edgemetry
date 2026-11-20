# SpanLens

Answer one question that classic APM tooling often cannot: **how long did our outbound call to a
specific endpoint actually take, and how is that trending?**

SpanLens receives OpenTelemetry spans over OTLP, stores them, and answers latency questions at the
span level — per caller service, per callee address, per operation, with p50/p95/p99 and error rate.
It sits next to an existing APM, not instead of it: the APM keeps alerting on services, SpanLens
answers "the call to `payments.internal:8443` is 900 ms at p95" when the metrics-only UI cannot.

## Why

Metrics lose the callee. A metric named `outbound.duration` with dimensions `service` and `status`
cannot tell you which remote endpoint was slow, because the peer address is unbounded and most
metrics backends refuse high-cardinality dimensions. Spans carry the peer, the operation and the
timing, but many managed APM editions expose only trace-by-id lookup — no aggregation over spans.

SpanLens stores the spans and runs the aggregation.

## Quickstart

```bash
python -m venv .venv
.venv/bin/pip install -e ".[otlp,postgres]"   # drop the extras for a JSON-only, SQLite-only run

# receiver + query API
PYTHONPATH=src .venv/bin/python -m spanlens.cli serve --db spans.db --port 4318

# in another shell: emit demo traffic with known latency
PYTHONPATH=src .venv/bin/python demo/emit_demo.py

# aggregate query
PYTHONPATH=src .venv/bin/python -m spanlens.cli query --db spans.db --since 3600
```

Output from a real run of the demo (400 calls, target sleeps 200 ms normally and 900 ms one call in
four, fails one call in twenty):

```
service           peer                      span                       n     p50     p95     p99   err%
-------------------------------------------------------------------------------------------------------
gateway           payments.internal:8443    POST                     400  202.06  902.22  902.42    6.5
```

The ground truth is 200/900 ms and 5 % errors; the measured percentiles match it.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/traces` | OTLP/HTTP export — protobuf and JSON both accepted |
| GET | `/v1/edges?since=3600&service=gateway&kind=client` | latency per caller → callee edge |
| GET | `/v1/traces/{trace_id}` | waterfall with computed self time |
| GET | `/health` | liveness |

Content type decides the decoder: `application/x-protobuf` uses the official OTLP generated classes,
anything else is parsed as OTLP/JSON. A deployment without `opentelemetry-proto` installed answers
`415` on protobuf instead of failing silently.

## Sending real traces

Native protobuf, no encoder flag needed:

```yaml
exporters:
  otlphttp/spanlens:
    traces_endpoint: http://spanlens:4318/v1/traces
```

## Running next to Dynatrace

`deploy/otel-collector-dynatrace.yaml` exports every span twice: unchanged to Dynatrace, and to
SpanLens. Nothing in the application changes, and the Dynatrace path keeps its own sampling and
billing.

After wiring it, check that the spans actually carry a callee:

```bash
PYTHONPATH=src .venv/bin/python -m spanlens.cli verify --since 3600
```

```
service                   client spans  missing peer   coverage
---------------------------------------------------------------
gateway                            400             0     100.0%
legacy-api                          60            60       0.0%

1 service(s) below 95% coverage: no callee on the span, so per-endpoint latency cannot be computed
```

Exit code 2 means broken instrumentation — a client span without a peer cannot answer "which remote
endpoint is slow", and no amount of querying fixes that. The collector config normalises
`server.address`, `peer.service` and `net.peer.name` into one attribute before export.

## Storage backends

| Backend | Flag | Percentiles | Use |
|---|---|---|---|
| SQLite | `--db spans.db` | computed in Python | single node, pilot, zero setup |
| PostgreSQL | `--backend postgres --dsn ...` | `percentile_cont` in the database | the scale path |

Measured on 100 000 client spans, same aggregate query, this machine:

```
sqlite      100000 span  yazma   1.76s  sorgu medyan   628.1 ms
postgres    100000 span  yazma   1.98s  sorgu medyan   191.7 ms
```

Postgres answers 3.3× faster because the percentile is computed next to the data instead of pulling
every duration into the process. Ingest uses `COPY`, which is what keeps write time level with SQLite.

**ClickHouse and DuckDB were tried and do not run on this host**: both crash with `Illegal instruction`
because the CPU has no AVX2. On normal server hardware they remain the better long-term store; the
`Store` interface is deliberately narrow so swapping one in touches no query code.

## Design notes

- **Nanoseconds inside, milliseconds at the edge.** OTLP sends epoch nanoseconds as decimal strings;
  every stored value is an integer nanosecond, conversion happens only when printing.
- **Self time is computed, not stored.** `self = parent.duration − sum(children.duration)`. A backend
  that returns a flat span list cannot answer "where did the time go" without this step.
- **Sampling changes the meaning of the answer.** If the collector samples traces, counts are a
  sample, not request totals. Report rates and percentiles, never totals.

## Limits of v0.1

- Single node, one process. No retention policy — the database grows forever.
- No authentication on the receiver. Put it behind the collector's network boundary.
- No histogram or time-series rollups yet; every query scans the window.
- `verify` checks one attribute family; it does not validate OTLP conformance.

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

Eight tests cover the nearest-rank percentile, nanosecond parsing, peer extraction, protobuf decoding,
error rate, edge grouping, peer coverage and self-time computation.
