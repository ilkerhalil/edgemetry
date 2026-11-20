"""OTLP/protobuf decoding against the official generated classes."""

from __future__ import annotations

import pytest

pytest.importorskip("opentelemetry.proto")

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from edgemetry.otlp_proto import parse_otlp_protobuf, protobuf_available


def build_request() -> ExportTraceServiceRequest:
    request = ExportTraceServiceRequest()
    resource_span = request.resource_spans.add()
    attr = resource_span.resource.attributes.add()
    attr.key = "service.name"
    attr.value.string_value = "payments"

    scope_span = resource_span.scope_spans.add()
    span = scope_span.spans.add()
    span.trace_id = bytes.fromhex("aa" * 16)
    span.span_id = bytes.fromhex("bb" * 8)
    span.name = "POST /charge"
    span.kind = 3
    span.start_time_unix_nano = 1_000_000_000
    span.end_time_unix_nano = 1_050_000_000
    span.status.code = 2

    address = span.attributes.add()
    address.key = "server.address"
    address.value.string_value = "bank.example"
    port = span.attributes.add()
    port.key = "server.port"
    port.value.int_value = 8443
    return request


def test_protobuf_is_available() -> None:
    assert protobuf_available() is True


def test_decodes_bytes_to_span_model() -> None:
    spans = parse_otlp_protobuf(build_request().SerializeToString())
    assert len(spans) == 1
    parsed = spans[0]
    assert parsed.service == "payments"
    assert parsed.trace_id == "aa" * 16
    assert parsed.span_id == "bb" * 8
    assert parsed.duration_ns == 50_000_000
    assert parsed.peer == "bank.example:8443"
    assert parsed.status == "error"
    assert parsed.kind == "client"


def test_empty_bytes_yield_no_spans() -> None:
    assert parse_otlp_protobuf(b"") == []
