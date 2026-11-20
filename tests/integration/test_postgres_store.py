"""PostgreSQL backend, exercised against a real server.

Skipped unless SPANLENS_TEST_DSN points at a reachable database. CI provides one
through a service container, which is why this is an integration test rather than
a mock: the whole point of the backend is that the database computes the
percentiles.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest

pytest.importorskip("psycopg")

from spanlens.store_pg import PostgresStore

DSN = os.environ.get("SPANLENS_TEST_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="SPANLENS_TEST_DSN not set")


@pytest.fixture
def pg_store():
    store = PostgresStore(DSN)
    store.conn.execute("TRUNCATE spans")
    try:
        yield store
    finally:
        store.close()


def make(span_id: str, duration_ms: int, **overrides):
    from spanlens.model import Span

    now = time.time_ns()
    values = {
        "trace_id": uuid.uuid4().hex,
        "span_id": span_id,
        "parent_span_id": "",
        "service": "gateway",
        "name": "POST",
        "kind": "client",
        "start_ns": now,
        "end_ns": now + duration_ms * 1_000_000,
        "status": "ok",
        "peer": "payments.internal:8443",
        "attrs": {},
    }
    values.update(overrides)
    return Span(**values)


def test_edges_computes_percentiles_in_the_database(pg_store) -> None:
    pg_store.insert([make(f"t{i}", ms) for i, ms in enumerate((100, 200, 900, 900, 200))])
    rows = pg_store.edges(since_s=600)
    assert len(rows) == 1
    row = rows[0]
    assert row["count"] == 5
    assert row["p50_ms"] == 200.0
    assert row["p95_ms"] == 900.0
    assert row["span"] == "POST"


def test_error_rate_is_a_percentage(pg_store) -> None:
    pg_store.insert(
        [
            make("a", 10, status="error"),
            make("b", 10),
        ]
    )
    assert pg_store.edges(since_s=600)[0]["error_rate"] == 50.0


def test_peer_filter_is_a_substring_match(pg_store) -> None:
    pg_store.insert([make("a", 10)])
    assert pg_store.edges(since_s=600, peer="payments")[0]["count"] == 1
    assert pg_store.edges(since_s=600, peer="nothing-here") == []


def test_trace_waterfall(pg_store) -> None:
    now = time.time_ns()
    trace_id = "same-trace"
    pg_store.insert(
        [
            make(
                "root",
                100,
                trace_id=trace_id,
                kind="server",
                start_ns=now,
                end_ns=now + 100_000_000,
                peer="",
            ),
            make(
                "child",
                60,
                trace_id=trace_id,
                parent_span_id="root",
                start_ns=now + 10_000_000,
                end_ns=now + 70_000_000,
            ),
        ]
    )
    tree = pg_store.trace(trace_id)
    assert tree[0]["self_ns"] == 40_000_000
    assert tree[0]["children"][0]["span_id"] == "child"


def test_peer_coverage(pg_store) -> None:
    pg_store.insert(
        [
            make("a", 10),
            make("b", 10, peer=""),
            make("c", 10, peer=""),
        ]
    )
    rows = pg_store.peer_coverage(since_s=600)
    assert rows[0]["coverage_pct"] == 33.3
