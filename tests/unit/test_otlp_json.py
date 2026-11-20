"""OTLP/JSON decoding."""

from __future__ import annotations

from edgemetry.model import parse_otlp_json

PAYLOAD = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "gateway"}},
                ]
            },
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "traceId": "abc",
                            "spanId": "def",
                            "parentSpanId": "",
                            "name": "GET",
                            "kind": 3,
                            "startTimeUnixNano": "1700000000000000000",
                            "endTimeUnixNano": "1700000000050000000",
                            "status": {"code": 2},
                            "attributes": [
                                {"key": "server.address", "value": {"stringValue": "api.example"}},
                                {"key": "server.port", "value": {"intValue": "443"}},
                            ],
                        }
                    ]
                }
            ],
        }
    ]
}


def test_decodes_service_and_timing() -> None:
    spans = parse_otlp_json(PAYLOAD)
    assert len(spans) == 1
    span = spans[0]
    assert span.service == "gateway"
    assert span.duration_ns == 50_000_000
    assert span.kind == "client"
    assert span.status == "error"


def test_peer_is_host_and_port() -> None:
    assert parse_otlp_json(PAYLOAD)[0].peer == "api.example:443"


def test_empty_payload_yields_no_spans() -> None:
    assert parse_otlp_json({}) == []


def test_unknown_service_name_is_not_dropped() -> None:
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "t",
                                "spanId": "s",
                                "name": "x",
                                "kind": 1,
                                "startTimeUnixNano": "0",
                                "endTimeUnixNano": "1000",
                            }
                        ]
                    }
                ]
            }
        ]
    }
    spans = parse_otlp_json(payload)
    assert spans[0].service == "unknown_service"
    assert spans[0].kind == "internal"
    assert spans[0].status == "unset"
