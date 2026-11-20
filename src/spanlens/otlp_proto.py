"""OTLP/protobuf ingest.

JSON is a debug format; every real SDK and collector defaults to protobuf. Decoding
uses the official generated classes so the wire format never drifts from the spec.
The dependency is optional: a JSON-only deployment keeps working without it.
"""

from __future__ import annotations

from typing import Any

from .model import KINDS, STATUS, Span, pick_peer

try:  # pragma: no cover - import guard
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
except ImportError:  # pragma: no cover
    ExportTraceServiceRequest = None  # type: ignore[assignment]


def _any_value(value: Any) -> Any:
    kind = value.WhichOneof("value")
    if kind is None:
        return None
    return getattr(value, kind)


def _attributes(items) -> dict[str, Any]:
    return {item.key: _any_value(item.value) for item in items if item.key}


def protobuf_available() -> bool:
    return ExportTraceServiceRequest is not None


def parse_otlp_protobuf(body: bytes) -> list[Span]:
    """Decode an ExportTraceServiceRequest into the internal span model."""
    if ExportTraceServiceRequest is None:
        raise RuntimeError(
            "protobuf ingest requires the 'opentelemetry-proto' package: "
            "pip install spanlens[otlp]"
        )
    request = ExportTraceServiceRequest()
    request.ParseFromString(body)
    spans: list[Span] = []
    for resource_span in request.resource_spans:
        resource_attrs = _attributes(resource_span.resource.attributes)
        service = str(resource_attrs.get("service.name") or "unknown_service")
        for scope_span in resource_span.scope_spans:
            for raw in scope_span.spans:
                attrs = _attributes(raw.attributes)
                spans.append(
                    Span(
                        trace_id=raw.trace_id.hex(),
                        span_id=raw.span_id.hex(),
                        parent_span_id=raw.parent_span_id.hex(),
                        service=service,
                        name=raw.name,
                        kind=KINDS.get(int(raw.kind), "unspecified"),
                        start_ns=int(raw.start_time_unix_nano),
                        end_ns=int(raw.end_time_unix_nano),
                        status=STATUS.get(int(raw.status.code), "unset"),
                        peer=pick_peer(attrs),
                        attrs=attrs,
                    )
                )
    return spans
