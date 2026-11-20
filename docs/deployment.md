# Deployment

Two shapes: a pilot on one host with SQLite, and a service with PostgreSQL behind the collector.

## Pilot — one host

```bash
python -m venv /opt/spanlens/venv
/opt/spanlens/venv/bin/pip install "spanlens[otlp,postgres]"

# receiver
/opt/spanlens/venv/bin/spanlens serve --db /var/lib/spanlens/spans.db --port 4318
```

## systemd unit

```ini
[Unit]
Description=SpanLens span store
After=network-online.target

[Service]
User=spanlens
ExecStart=/opt/spanlens/venv/bin/spanlens serve --db /var/lib/spanlens/spans.db --port 4318
Restart=always
RestartSec=3
# the receiver only needs its own data directory
ProtectSystem=strict
ReadWritePaths=/var/lib/spanlens
NoNewPrivileges=true
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

## PostgreSQL

```bash
spanlens serve \
  --backend postgres \
  --dsn "postgresql://spanlens:secret@db.internal:5432/spanlens" \
  --port 4318
```

The schema is created on start. The user needs `CREATE TABLE` and `CREATE INDEX` on first run, and
`INSERT`/`SELECT` afterwards. Ingest uses `COPY`, so no superuser rights are required.

## Collector wiring

```yaml
exporters:
  otlphttp/dynatrace:
    endpoint: ${env:DT_ENDPOINT}
    headers:
      Authorization: "Api-Token ${env:DT_API_TOKEN}"
  otlphttp/spanlens:
    traces_endpoint: http://spanlens.internal:4318/v1/traces

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [transform/peer, batch]
      exporters: [otlphttp/dynatrace, otlphttp/spanlens]
```

A complete config with the peer-normalising transform is in
[`deploy/otel-collector-dynatrace.yaml`](../deploy/otel-collector-dynatrace.yaml).

## First checks after wiring

```bash
curl -s localhost:4318/health
spanlens verify --since 900
```

`verify` exits `2` when a service sends client spans without a callee. That is the one failure mode
that makes every later query meaningless, so fix it before tuning anything else.

## Capacity notes

Measured on one host with 100 000 client spans:

```
sqlite      yazma 1.76s   sorgu medyan 628.1 ms
postgres    yazma 1.98s   sorgu medyan 191.7 ms
```

A single span row is roughly 300 bytes with attributes; budget disk accordingly and prune the window
you actually query. There is no retention job in v0.1 — a `DELETE FROM spans WHERE start_ns < ?`
cron is the minimal stopgap.

## Security boundary

The receiver has no authentication. Bind it to loopback or a private interface, and let only the
collector reach it:

```bash
spanlens serve --host 10.0.4.12 --port 4318
```

If the network is not trusted, terminate mTLS in the collector's exporter rather than adding a
home-grown token check to the receiver.
