"""Bearer auth and the health contract, exercised over real HTTP."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from edgemetry.api import make_server

TOKEN = "s3cret-token"


def request(
    url: str, method: str = "GET", body: bytes | None = None, headers: dict[str, str] | None = None
) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


@pytest.fixture
def guarded(store):
    server = make_server(store, "127.0.0.1", 0, token=TOKEN)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


BATCH = {
    "resourceSpans": [
        {
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "gw"}}]},
            "scopeSpans": [
                {
                    "spans": [
                        {
                            "traceId": "aa",
                            "spanId": "bb",
                            "name": "POST",
                            "kind": 3,
                            "startTimeUnixNano": "1000000000",
                            "endTimeUnixNano": "1000500000",
                            "attributes": [
                                {"key": "server.address", "value": {"stringValue": "x"}}
                            ],
                        }
                    ]
                }
            ],
        }
    ]
}


def test_ingest_without_token_is_rejected(guarded: str) -> None:
    status, body = request(
        f"{guarded}/v1/traces",
        "POST",
        json.dumps(BATCH).encode(),
        {"Content-Type": "application/json"},
    )
    assert status == 401
    assert body["error"] == "unauthorized"


def test_ingest_with_wrong_token_is_rejected(guarded: str) -> None:
    status, _ = request(
        f"{guarded}/v1/traces",
        "POST",
        json.dumps(BATCH).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer nope"},
    )
    assert status == 401


def test_ingest_with_token_is_accepted(guarded: str) -> None:
    status, body = request(
        f"{guarded}/v1/traces",
        "POST",
        json.dumps(BATCH).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {TOKEN}"},
    )
    assert status == 200
    assert body["accepted"] == 1


def test_queries_require_the_token(guarded: str) -> None:
    assert request(f"{guarded}/v1/edges")[0] == 401
    status, body = request(f"{guarded}/v1/edges", headers={"Authorization": f"Bearer {TOKEN}"})
    assert status == 200
    assert "edges" in body


def test_health_stays_public(guarded: str) -> None:
    status, body = request(f"{guarded}/health")
    assert status == 200
    assert body["store"] == "ok"


def test_health_reports_a_dead_store(store) -> None:
    store.close()
    server = make_server(store, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = request(f"http://127.0.0.1:{server.server_address[1]}/health")
        assert status == 503
        assert body["status"] == "degraded"
    finally:
        server.shutdown()
        server.server_close()


def test_store_failure_on_ingest_returns_503(store) -> None:
    class BrokenStore:
        def insert(self, spans):
            raise RuntimeError("disk gone")

    server = make_server(BrokenStore(), "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        status, body = request(
            f"http://127.0.0.1:{server.server_address[1]}/v1/traces",
            "POST",
            json.dumps(BATCH).encode(),
            {"Content-Type": "application/json"},
        )
        assert status == 503
        assert "store unavailable" in body["error"]
    finally:
        server.shutdown()
        server.server_close()
