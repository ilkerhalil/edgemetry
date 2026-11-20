# HTTP API

Base URL in the examples: `http://127.0.0.1:4318`.

## Authentication

When the server runs with `EDGEMETRY_TOKEN` set, every endpoint except `/health` requires:

```
Authorization: Bearer <token>
```

Missing or wrong credentials return `401` with `WWW-Authenticate: Bearer realm="edgemetry"`.
Comparison is constant-time. Without a token the receiver accepts unauthenticated traffic and prints
`auth=NO AUTH` on startup.

## `POST /v1/traces`

Accepts an OTLP export request. The decoder is chosen by `Content-Type`:

| Content-Type | Decoder |
|---|---|
| `application/x-protobuf` | official OTLP generated classes (`edgemetry[otlp]`) |
| `application/protobuf`, `application/octet-stream` | same |
| anything else | OTLP/JSON |

Response `200`:

```json
{"accepted": 42}
```

`accepted` is the number of spans handed to the store. Re-sending the same span id is a no-op for
SQLite and PostgreSQL, so a collector retry does not inflate counts.

Errors:

| Code | Meaning |
|---|---|
| 400 | body is not valid for the declared encoding |
| 404 | path is not an ingest endpoint |
| 415 | protobuf body received but `opentelemetry-proto` is not installed |
| 401 | missing or wrong bearer token |
| 503 | the store failed while writing the batch |

## `GET /v1/edges`

Latency per `(caller service, callee peer, span name)`.

| Parameter | Default | Meaning |
|---|---|---|
| `since` | `3600` | window in seconds, counted back from now |
| `service` | all | exact match on the caller |
| `peer` | all | substring match on the callee |
| `kind` | `client` | `client`, `server`, `internal`, `producer`, `consumer` |
| `limit` | `50` | maximum rows, sorted by p95 descending |

```json
{
  "edges": [
    {
      "service": "gateway",
      "peer": "payments.internal:8443",
      "span": "POST",
      "count": 400,
      "error_rate": 6.5,
      "p50_ms": 202.06,
      "p95_ms": 902.22,
      "p99_ms": 902.42,
      "max_ms": 902.52
    }
  ]
}
```

All durations are **milliseconds** in the response; the store keeps nanoseconds.

## `GET /v1/traces/{trace_id}`

Full waterfall for one trace, with `self_ns` computed per span.

```json
{
  "trace_id": "00d6d13c99894ec7a2b07f156819a6d5",
  "spans": [
    {
      "span_id": "78c4989c44d442aa",
      "parent_span_id": "",
      "service": "checkout-api",
      "name": "POST /checkout",
      "kind": "server",
      "peer": "",
      "duration_ns": 206660962,
      "self_ns": 5000000,
      "status": "ok",
      "children": [
        {
          "span_id": "a02831c04efb49c6",
          "service": "gateway",
          "name": "POST",
          "kind": "client",
          "peer": "payments.internal:8443",
          "duration_ns": 201660962,
          "self_ns": 201660962,
          "children": []
        }
      ]
    }
  ]
}
```

`404` when no span carries that trace id.

## `GET /health`

```json
{"status": "ok", "store": "ok"}
```

Returns `503` with `{"status": "degraded", "store": "down"}` when the store stops answering, so a load
balancer takes the node out instead of sending it traffic. Always public, never requires the token.

## CLI equivalent

```bash
edgemetry query --since 3600 --service gateway
edgemetry trace 00d6d13c99894ec7a2b07f156819a6d5
edgemetry verify --since 3600
```
