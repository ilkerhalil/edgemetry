# Edgemetry — a span-level latency store

Your metrics say `outbound.duration` is up. They cannot say which outbound call.

That is not a data problem, it is a cardinality problem: the callee address would be an unbounded
dimension, so most metric backends refuse it. Spans carry the address, the operation and the timing,
but trace-by-id lookup is often all you get — no aggregation over spans, no span search.

Edgemetry stores the spans and answers the narrow question: how long did calls from this service to
this endpoint take, at p50/p95/p99, and what share failed.

It runs beside the collector, not in the request path:

```yaml
exporters:
  otlphttp/edgemetry:
    traces_endpoint: http://edgemetry:4318/v1/traces
    headers:
      Authorization: "Bearer ${env:EDGEMETRY_TOKEN}"
```

Measured, not claimed. 400 requests against a fake payments API with known latency — 200 ms normal,
900 ms every fourth call, 5 % error:

```
service     peer                      span     n     p50     p95     p99   err%
checkout    payments.internal:8443    POST   400  202.06  902.22  902.42    6.5
```

100 000 spans, two backends: SQLite writes in 1.76 s and queries in 628 ms; PostgreSQL writes in
1.98 s and queries in 192 ms, 3.3× faster. ClickHouse did not run on this machine at all —
`Illegal instruction`, no AVX2 — so it is untested here, not rejected.

There is a `verify` command for the silent failure mode: spans without a callee make every query
return nothing while the row count looks healthy. It exits 2 when a service falls below 95 % coverage,
so a install script or CI job can refuse to call the setup done.

Honest limits: single node, no trend rollups, shared-secret auth rather than per-tenant authorisation,
no TLS, and it has not yet been pointed at a live enterprise APM environment. Ingest throughput is
unmeasured; 100 000 spans is a batch test, not a rate.

```
pip install "edgemetry[otlp,postgres]"
```

Zero dependencies in the core — stdlib and SQLite; protobuf and PostgreSQL are optional extras.
73 tests, 90 % coverage, CI green on Python 3.11–3.13.

https://github.com/ilkerhalil/edgemetry
