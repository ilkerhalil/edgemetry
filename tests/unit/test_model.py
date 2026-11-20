"""Span model: duration derivation, peer selection and the waterfall builder."""

from __future__ import annotations

from edgemetry.model import build_tree, pick_peer


def test_duration_is_end_minus_start() -> None:
    from edgemetry.model import Span

    span = Span(
        trace_id="t",
        span_id="s",
        parent_span_id="",
        service="svc",
        name="GET",
        kind="client",
        start_ns=1_000_000,
        end_ns=1_250_000,
        status="ok",
        peer="",
        attrs={},
    )
    assert span.duration_ns == 250_000


def test_peer_prefers_normalised_attribute() -> None:
    attrs = {"edgemetry.peer": "canonical", "server.address": "raw"}
    assert pick_peer(attrs) == "canonical"


def test_peer_joins_host_and_port() -> None:
    assert pick_peer({"server.address": "api.example", "server.port": "443"}) == "api.example:443"


def test_peer_falls_back_to_db_system() -> None:
    assert pick_peer({"db.system": "postgresql"}) == "postgresql"


def test_peer_empty_when_nothing_present() -> None:
    assert pick_peer({}) == ""


def test_build_tree_computes_self_time() -> None:
    rows = [
        {"span_id": "root", "parent_span_id": "", "duration_ns": 100, "service": "a"},
        {"span_id": "child", "parent_span_id": "root", "duration_ns": 60, "service": "b"},
    ]
    tree = build_tree(rows)
    assert len(tree) == 1
    root = tree[0]
    assert root["self_ns"] == 40
    assert root["children"][0]["span_id"] == "child"


def test_build_tree_never_returns_negative_self_time() -> None:
    rows = [
        {"span_id": "root", "parent_span_id": "", "duration_ns": 50, "service": "a"},
        {"span_id": "child", "parent_span_id": "root", "duration_ns": 80, "service": "b"},
    ]
    assert build_tree(rows)[0]["self_ns"] == 0


def test_build_tree_handles_orphans() -> None:
    rows = [{"span_id": "orphan", "parent_span_id": "missing", "duration_ns": 10, "service": "a"}]
    assert build_tree(rows) == []
