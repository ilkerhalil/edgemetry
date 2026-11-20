"""SQLite store behaviour: grouping, filtering, coverage and waterfalls."""

from __future__ import annotations

from spanlens.store import Store

NOW = 10**18


def test_edges_group_by_service_peer_and_name(store: Store, make_span) -> None:
    for i, ms in enumerate((100, 200, 900, 900, 200)):
        store.insert(
            [
                make_span(
                    span_id=f"s{i}",
                    start_ns=NOW,
                    end_ns=NOW + ms * 1_000_000,
                )
            ]
        )

    rows = store.edges(since_s=10**9)
    assert len(rows) == 1
    row = rows[0]
    assert row["count"] == 5
    assert row["p50_ms"] == 200.0
    assert row["max_ms"] == 900.0
    assert row["error_rate"] == 0.0


def test_edges_counts_errors_as_percentage(store: Store, make_span) -> None:
    store.insert(
        [
            make_span(span_id="a", status="error", start_ns=NOW, end_ns=NOW + 10**6),
            make_span(span_id="b", status="ok", start_ns=NOW, end_ns=NOW + 20 * 10**6),
        ]
    )
    assert store.edges(since_s=10**9)[0]["error_rate"] == 50.0


def test_edges_respects_service_filter(store: Store, make_span) -> None:
    store.insert(
        [
            make_span(span_id="a", service="gateway", start_ns=NOW, end_ns=NOW + 10**6),
            make_span(
                span_id="b", service="billing", start_ns=NOW, end_ns=NOW + 10**6, peer="ledger:5432"
            ),
        ]
    )
    rows = store.edges(since_s=10**9, service="billing")
    assert [r["service"] for r in rows] == ["billing"]


def test_edges_filters_by_kind(store: Store, make_span) -> None:
    store.insert([make_span(span_id="a", kind="server", start_ns=NOW, end_ns=NOW + 10**6)])
    assert store.edges(since_s=10**9, kind="client") == []


def test_edges_ignore_spans_outside_window(store: Store, make_span) -> None:
    store.insert([make_span(span_id="old", start_ns=0, end_ns=10**6)])
    assert store.edges(since_s=60) == []


def test_insert_is_idempotent_per_span_id(store: Store, make_span) -> None:
    span = make_span(span_id="dup", start_ns=NOW, end_ns=NOW + 10**6)
    store.insert([span])
    store.insert([span])
    assert store.edges(since_s=10**9)[0]["count"] == 1


def test_trace_returns_nested_waterfall(store: Store, make_span) -> None:
    store.insert(
        [
            make_span(span_id="root", kind="server", start_ns=0, end_ns=100_000_000),
            make_span(
                span_id="child",
                parent_span_id="root",
                kind="client",
                start_ns=10_000_000,
                end_ns=70_000_000,
            ),
        ]
    )
    tree = store.trace("t1")
    assert tree[0]["duration_ns"] == 100_000_000
    assert tree[0]["self_ns"] == 40_000_000
    assert tree[0]["children"][0]["duration_ns"] == 60_000_000


def test_trace_unknown_id_returns_empty(store: Store) -> None:
    assert store.trace("nope") == []


def test_peer_coverage_flags_missing_callee(store: Store, make_span) -> None:
    store.insert(
        [
            make_span(span_id="a", peer="payments:8443", start_ns=NOW, end_ns=NOW + 10**6),
            make_span(span_id="b", peer="", start_ns=NOW, end_ns=NOW + 10**6),
            make_span(span_id="c", peer="", start_ns=NOW, end_ns=NOW + 10**6),
            make_span(span_id="d", peer="", kind="server", start_ns=NOW, end_ns=NOW + 10**6),
        ]
    )
    rows = store.peer_coverage(since_s=10**9)
    assert len(rows) == 1
    assert rows[0]["client_spans"] == 3
    assert rows[0]["missing_peer"] == 2
    assert rows[0]["coverage_pct"] == 33.3
