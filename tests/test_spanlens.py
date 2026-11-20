from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spanlens.model import Span, parse_otlp_json  # noqa: E402
from spanlens.store import Store, percentile  # noqa: E402


def make_span(**kw) -> Span:
    base = dict(
        trace_id="t1", span_id="s1", parent_span_id="", service="gw", name="POST",
        kind="client", start_ns=1_000, end_ns=6_000, status="ok",
        peer="payments.internal:8443", attrs={},
    )
    base.update(kw)
    return Span(**base)


def test_percentile_nearest_rank() -> None:
    values = [10, 20, 30, 40, 50]
    assert percentile(values, 50) == 30
    assert percentile(values, 95) == 48.0
    assert percentile([], 95) == 0.0
    assert percentile([7], 99) == 7.0


def test_duration_is_derived_from_timestamps() -> None:
    span = make_span(start_ns=1_000_000, end_ns=1_250_000)
    assert span.duration_ns == 250_000


def test_parse_otlp_nanosecond_strings() -> None:
    payload = {
        "resourceSpans": [{
            "resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": "gateway"}}]},
            "scopeSpans": [{"spans": [{
                "traceId": "abc", "spanId": "def", "parentSpanId": "",
                "name": "GET", "kind": 3,
                "startTimeUnixNano": "1700000000000000000",
                "endTimeUnixNano": "1700000000050000000",
                "status": {"code": 2},
                "attributes": [
                    {"key": "server.address", "value": {"stringValue": "api.example"}},
                    {"key": "server.port", "value": {"intValue": "443"}},
                ],
            }]}],
        }]
    }
    spans = parse_otlp_json(payload)
    assert len(spans) == 1
    span = spans[0]
    assert span.service == "gateway"
    assert span.duration_ns == 50_000_000
    assert span.peer == "api.example:443"
    assert span.kind == "client"
    assert span.status == "error"


def test_edges_groups_and_computes_percentiles(tmp_path) -> None:
    store = Store(tmp_path / "s.db")
    try:
        for ms in (100, 200, 900, 900, 200):
            store.insert([make_span(
                span_id=f"s{ms}{random_suffix()}",
                start_ns=10**18, end_ns=10**18 + ms * 1_000_000,
            )])
        rows = store.edges(since_s=10**9)
        assert len(rows) == 1
        row = rows[0]
        assert row["count"] == 5
        assert row["p50_ms"] == 200.0
        assert row["max_ms"] == 900.0
        assert row["error_rate"] == 0.0
    finally:
        store.close()


_counter = iter(range(10000))


def random_suffix() -> str:
    return str(next(_counter))


def test_edges_counts_errors(tmp_path) -> None:
    store = Store(tmp_path / "e.db")
    try:
        store.insert([
            make_span(span_id="a", status="error", start_ns=10**18, end_ns=10**18 + 10**6),
            make_span(span_id="b", status="ok", start_ns=10**18, end_ns=10**18 + 20 * 10**6),
        ])
        row = store.edges(since_s=10**9)[0]
        assert row["error_rate"] == 50.0
    finally:
        store.close()


def test_trace_self_time(tmp_path) -> None:
    store = Store(tmp_path / "t.db")
    try:
        store.insert([
            make_span(span_id="root", kind="server", start_ns=0, end_ns=100_000_000),
            make_span(span_id="child", parent_span_id="root", kind="client",
                      start_ns=10_000_000, end_ns=70_000_000),
        ])
        tree = store.trace("t1")
        assert tree[0]["duration_ns"] == 100_000_000
        assert tree[0]["self_ns"] == 40_000_000
        assert tree[0]["children"][0]["duration_ns"] == 60_000_000
    finally:
        store.close()
