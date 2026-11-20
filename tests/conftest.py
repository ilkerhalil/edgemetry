"""Shared fixtures: a store per test, a span factory, and a live HTTP server."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator

import pytest

from spanlens.api import make_server
from spanlens.model import Span
from spanlens.store import Store


@pytest.fixture
def store(tmp_path) -> Iterator[Store]:
    db = Store(tmp_path / "spans.db")
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def make_span() -> Callable[..., Span]:
    """Factory with sane defaults; pass only the fields the test cares about."""

    def factory(**overrides) -> Span:
        values = {
            "trace_id": "t1",
            "span_id": "s1",
            "parent_span_id": "",
            "service": "gateway",
            "name": "POST",
            "kind": "client",
            "start_ns": 1_000_000,
            "end_ns": 6_000_000,
            "status": "ok",
            "peer": "payments.internal:8443",
            "attrs": {},
        }
        values.update(overrides)
        return Span(**values)

    return factory


@pytest.fixture
def live_server(store) -> Iterator[str]:
    """Real HTTP server on an ephemeral port; yields its base URL."""
    server = make_server(store, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
