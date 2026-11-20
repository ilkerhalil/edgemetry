# SpanLens

Answer one question that classic APM tooling often cannot: **how long did our outbound call to a
specific endpoint actually take, and how is that trending?**

SpanLens receives OpenTelemetry spans over OTLP/HTTP, stores them, and answers latency questions at
the span level — per caller service, per callee address, per operation, with p50/p95/p99 and error
rate. It sits next to an existing APM, not instead of it: the APM keeps alerting on services, SpanLens
answers "the call to `payments.internal:8443` is 900 ms at p95" when the metrics-only UI cannot.

## Why

Metrics lose the callee. A metric named `outbound.duration` with dimensions `service` and `status`
cannot tell you which remote endpoint was slow, because the peer address is unbounded and most
metrics backends refuse high-cardinality dimensions. Spans carry the peer, the operation and the
timing, but many managed APM editions expose only trace-by-id lookup — no aggregation over spans.

SpanLens stores the spans and runs the aggregation.

## Quickstart

```bash
python -m venv .venv && .venv/bin/pip install -e .

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
| POST | `/v1/traces` | OTLP/HTTP JSON export, the standard collector endpoint |
| GET | `/v1/edges?since=3600&service=gateway&kind=client` | latency per caller → callee edge |
| GET | `/v1/traces/{trace_id}` | waterfall with computed self time |
| GET | `/health` | liveness |

## Sending real traces

Point an OpenTelemetry Collector at SpanLens with the JSON encoder:

```yaml
exporters:
  otlphttp/spanlens:
    traces_endpoint: http://spanlens:4318/v1/traces
    encoding: json
```

`encoding: json` is required in v0.1 — protobuf ingest is the next milestone.

## Design notes

- **Nanoseconds inside, milliseconds at the edge.** OTLP sends epoch nanoseconds as decimal strings;
  every stored value is an integer nanosecond, conversion happens only when printing.
- **Self time is computed, not stored.** `self = parent.duration − sum(children.duration)`. A backend
  that returns a flat span list cannot answer "where did the time go" without this step.
- **Sampling changes the meaning of the answer.** If the collector samples traces, counts are a
  sample, not request totals. Report rates and percentiles, never totals.

## Limits of v0.1

- SQLite storage, one process, single node. Fine for a pilot; ClickHouse is the scale path.
- OTLP/HTTP JSON only. Standard SDKs default to protobuf, so the collector must set `encoding: json`.
- Percentiles are computed in the application after a bounded row scan, not in the database.
- No retention policy yet — the demo database grows forever.

## Tests

```bash
.venv/bin/python -m pytest tests -q
```

Six tests cover the nearest-rank percentile, nanosecond parsing, peer extraction, error rate,
edge grouping and self-time computation.
