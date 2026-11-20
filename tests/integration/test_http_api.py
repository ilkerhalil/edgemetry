"""End-to-end over real HTTP: ingest by both encodings, then query back."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

pytest.importorskip("opentelemetry.proto")

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)


def post(url: str, body: bytes, content_type: str) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=body, headers={"Content-Type": content_type})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def get(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def json_batch(service: str, peer: str, duration_ms: int, count: int = 1) -> dict:
    import time

    now = time.time_ns()
    spans = [
        {
            "traceId": f"{i:032x}",
            "spanId": f"{i + 100:016x}",
            "parentSpanId": "",
            "name": "POST",
            "kind": 3,
            "startTimeUnixNano": str(now),
            "endTimeUnixNano": str(now + duration_ms * 1_000_000),
            "status": {"code": 1},
            "attributes": [
                {"key": "server.address", "value": {"stringValue": peer}},
                {"key": "server.port", "value": {"intValue": "8443"}},
            ],
        }
        for i in range(count)
    ]
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": service}}]
                },
                "scopeSpans": [{"spans": spans}],
            }
        ]
    }


def test_health(live_server: str) -> None:
    status, body = get(f"{live_server}/health")
    assert status == 200
    assert body["status"] == "ok"


def test_json_ingest_then_query(live_server: str) -> None:
    status, body = post(
        f"{live_server}/v1/traces",
        json.dumps(json_batch("gateway", "payments.internal", 250)).encode(),
        "application/json",
    )
    assert status == 200
    assert body["accepted"] == 1

    status, body = get(f"{live_server}/v1/edges?since=600")
    assert status == 200
    edge = body["edges"][0]
    assert edge["service"] == "gateway"
    assert edge["peer"] == "payments.internal:8443"
    assert edge["p50_ms"] == pytest.approx(250, abs=5)


def test_protobuf_ingest_then_query(live_server: str) -> None:
    request = ExportTraceServiceRequest()
    resource_span = request.resource_spans.add()
    name = resource_span.resource.attributes.add()
    name.key = "service.name"
    name.value.string_value = "billing"
    span = resource_span.scope_spans.add().spans.add()
    span.trace_id = bytes.fromhex("cc" * 16)
    span.span_id = bytes.fromhex("dd" * 8)
    span.name = "GET"
    span.kind = 3
    import time

    now = time.time_ns()
    span.start_time_unix_nano = now
    span.end_time_unix_nano = now + 90_000_000
    span.status.code = 1
    address = span.attributes.add()
    address.key = "server.address"
    address.value.string_value = "ledger.internal"

    status, body = post(
        f"{live_server}/v1/traces",
        request.SerializeToString(),
        "application/x-protobuf",
    )
    assert status == 200
    assert body["accepted"] == 1

    status, body = get(f"{live_server}/v1/edges?since=600&service=billing")
    assert status == 200
    assert body["edges"][0]["peer"] == "ledger.internal"


def test_trace_waterfall_endpoint(live_server: str) -> None:
    post(
        f"{live_server}/v1/traces",
        json.dumps(json_batch("gateway", "payments.internal", 120)).encode(),
        "application/json",
    )
    status, body = get(f"{live_server}/v1/traces/{0:032x}")
    assert status == 200
    assert body["spans"][0]["self_ns"] > 0


def test_unknown_trace_returns_404(live_server: str) -> None:
    status, body = get(f"{live_server}/v1/traces/does-not-exist")
    assert status == 404
    assert body["error"] == "trace not found"


def test_broken_json_returns_400(live_server: str) -> None:
    status, body = post(f"{live_server}/v1/traces", b"{not json", "application/json")
    assert status == 400
    assert "invalid json" in body["error"]


def test_invalid_query_parameter_returns_400(live_server: str) -> None:
    status, body = get(f"{live_server}/v1/edges?since=abc")
    assert status == 400
    assert "invalid query" in body["error"]


def test_unknown_path_returns_404(live_server: str) -> None:
    status, _ = get(f"{live_server}/nope")
    assert status == 404
