"""Span model and OTLP/JSON parsing.

OTLP numbers arrive as strings of epoch nanoseconds. Everything inside SpanLens is
nanoseconds; conversion to milliseconds happens only at the reporting edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

KINDS = {
    0: "unspecified",
    1: "internal",
    2: "server",
    3: "client",
    4: "producer",
    5: "consumer",
}

STATUS = {0: "unset", 1: "ok", 2: "error"}

# Attribute keys that identify the callee of a client span, in priority order.
PEER_KEYS = (
    "spanlens.peer",
    "server.address",
    "peer.service",
    "net.peer.name",
    "db.system",
    "rpc.service",
)


@dataclass(slots=True)
class Span:
    trace_id: str
    span_id: str
    parent_span_id: str
    service: str
    name: str
    kind: str
    start_ns: int
    end_ns: int
    status: str
    peer: str
    attrs: dict[str, Any]

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns


def _attr_value(value: dict[str, Any]) -> Any:
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            return value[key]
    return None


def flat_attributes(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in items or []:
        key = item.get("key")
        if key:
            out[key] = _attr_value(item.get("value") or {})
    return out


def service_name(resource_attrs: dict[str, Any]) -> str:
    name = resource_attrs.get("service.name")
    return str(name) if name else "unknown_service"


def pick_peer(attrs: dict[str, Any]) -> str:
    for key in PEER_KEYS:
        value = attrs.get(key)
        if value not in (None, ""):
            port = attrs.get("server.port") or attrs.get("net.peer.port")
            return f"{value}:{port}" if port and key.startswith("server.") else str(value)
    return ""


def _to_int(value: Any) -> int:
    """OTLP JSON sends uint64 as decimal strings."""
    if value in (None, ""):
        return 0
    return int(value)


def parse_otlp_json(payload: dict[str, Any]) -> list[Span]:
    spans: list[Span] = []
    for resource_span in payload.get("resourceSpans", []):
        resource_attrs = flat_attributes(
            (resource_span.get("resource") or {}).get("attributes")
        )
        service = service_name(resource_attrs)
        for scope_span in resource_span.get("scopeSpans", []):
            for raw in scope_span.get("spans", []):
                attrs = flat_attributes(raw.get("attributes"))
                spans.append(
                    Span(
                        trace_id=str(raw.get("traceId", "")),
                        span_id=str(raw.get("spanId", "")),
                        parent_span_id=str(raw.get("parentSpanId", "")),
                        service=service,
                        name=str(raw.get("name", "")),
                        kind=KINDS.get(raw.get("kind", 0), "unspecified"),
                        start_ns=_to_int(raw.get("startTimeUnixNano")),
                        end_ns=_to_int(raw.get("endTimeUnixNano")),
                        status=STATUS.get((raw.get("status") or {}).get("code", 0), "unset"),
                        peer=pick_peer(attrs),
                        attrs=attrs,
                    )
                )
    return spans


def build_tree(rows: list[dict]) -> list[dict]:
    """Turn a flat span list into a waterfall with computed self time."""
    children: dict[str, list[dict]] = {}
    for row in rows:
        children.setdefault(row.get("parent_span_id", ""), []).append(row)

    def build(node: dict) -> dict:
        kids = [build(k) for k in children.get(node["span_id"], [])]
        child_ns = sum(k["duration_ns"] for k in kids)
        out = dict(node)
        out["self_ns"] = max(node["duration_ns"] - child_ns, 0)
        out["children"] = kids
        return out

    return [build(r) for r in children.get("", [])]
