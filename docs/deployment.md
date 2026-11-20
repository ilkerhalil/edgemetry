# Deployment

Two shapes: a pilot on one host with SQLite, and a service with PostgreSQL behind the collector.

## Pilot — one host

```bash
python -m venv /opt/edgemetry/venv
/opt/edgemetry/venv/bin/pip install "edgemetry[otlp,postgres]"

# receiver
/opt/edgemetry/venv/bin/edgemetry serve --db /var/lib/edgemetry/spans.db --port 4318 \
  --retention 7d --token "$EDGEMETRY_TOKEN"
```

## systemd unit

```ini
[Unit]
Description=Edgemetry span store
After=network-online.target

[Service]
User=edgemetry
EnvironmentFile=/etc/edgemetry/env
ExecStart=/opt/edgemetry/venv/bin/edgemetry serve --db /var/lib/edgemetry/spans.db --port 4318 --retention 7d
Restart=always
RestartSec=3
# the receiver only needs its own data directory
ProtectSystem=strict
ReadWritePaths=/var/lib/edgemetry
NoNewPrivileges=true
MemoryMax=2G

[Install]
WantedBy=multi-user.target
```

## PostgreSQL

```bash
edgemetry serve \
  --backend postgres \
  --dsn "postgresql://edgemetry:secret@db.internal:5432/edgemetry" \
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
  otlphttp/edgemetry:
    traces_endpoint: http://edgemetry.internal:4318/v1/traces

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [transform/peer, batch]
      exporters: [otlphttp/dynatrace, otlphttp/edgemetry]
```

A complete config with the peer-normalising transform is in
[`deploy/otel-collector-dynatrace.yaml`](../deploy/otel-collector-dynatrace.yaml).

## First checks after wiring

```bash
curl -s localhost:4318/health
edgemetry verify --since 900
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
you actually query. `--retention 7d` runs at start and every six hours. For an ad-hoc prune:

```bash
edgemetry prune --older-than 7d --dry-run     # report
edgemetry prune --older-than 7d               # delete
```

## Security boundary

Two layers, use both:

```bash
# /etc/edgemetry/env
EDGEMETRY_TOKEN=<48 hex chars from openssl rand -hex 24>
```

```bash
edgemetry serve --host 10.0.4.12 --port 4318   # private interface, token from the env file
```

The collector exporter then sends the token:

```yaml
exporters:
  otlphttp/edgemetry:
    traces_endpoint: http://edgemetry.internal:4318/v1/traces
    headers:
      Authorization: "Bearer ${env:EDGEMETRY_TOKEN}"
```

The startup line states which mode is active: `auth=bearer token` or `auth=NO AUTH`. For mTLS,
terminate it in the collector's exporter rather than in the receiver.

Health check for the service manager:

```bash
curl -fsS localhost:4318/health || exit 1   # 503 when the store is down
```
