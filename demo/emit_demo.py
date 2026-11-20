"""Demo: emit real spans with known latency into a running SpanLens receiver.

Two services: a gateway calling a payment API. Half the calls are slow, one in
twenty fails. The delays are the ground truth; the query result must match them
within sampling noise — that is what makes the demo a measurement and not a
picture.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SPANLENS = os.environ.get("SPANLENS_URL", "http://127.0.0.1:4318/v1/traces")
random.seed(7)


def now_ns() -> int:
    return time.time_ns()


def hex_id(n: int = 16) -> str:
    return uuid.uuid4().hex[:n]


def otlp(spans: list[dict], service: str) -> dict:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": service}}]
                },
                "scopeSpans": [{"scope": {"name": "spanlens-demo"}, "spans": spans}],
            }
        ]
    }


def post(payload: dict) -> None:
    req = urllib.request.Request(
        SPANLENS,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req, timeout=5).read()


class Target(BaseHTTPRequestHandler):
    """Simulated payment API: 200 ms normally, 900 ms one call in four."""

    def log_message(self, *a) -> None:
        return

    def do_POST(self) -> None:
        slow = random.random() < 0.25
        time.sleep(0.9 if slow else 0.2)
        code = 500 if random.random() < 0.05 else 200
        self.send_response(code)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


def main(requests: int = 400) -> None:
    target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
    port = target.server_address[1]
    threading.Thread(target=target.serve_forever, daemon=True).start()
    print(f"target API on 127.0.0.1:{port}")

    sent = 0
    for _ in range(requests):
        trace_id = hex_id(32)
        parent_id = hex_id()
        start = now_ns()
        error = False
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/v1/payments",
                data=b'{"amount":10}',
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5).read()
        except urllib.error.HTTPError:
            error = True
        end = now_ns()

        client_span = {
            "traceId": trace_id,
            "spanId": hex_id(),
            "parentSpanId": parent_id,
            "name": "POST",
            "kind": 3,
            "startTimeUnixNano": str(start),
            "endTimeUnixNano": str(end),
            "status": {"code": 2 if error else 1},
            "attributes": [
                {"key": "server.address", "value": {"stringValue": "payments.internal"}},
                {"key": "server.port", "value": {"intValue": "8443"}},
                {"key": "http.request.method", "value": {"stringValue": "POST"}},
                {"key": "url.path", "value": {"stringValue": "/v1/payments"}},
            ],
        }
        parent = {
            "traceId": trace_id,
            "spanId": parent_id,
            "parentSpanId": "",
            "name": "POST /checkout",
            "kind": 2,
            "startTimeUnixNano": str(start - 3_000_000),
            "endTimeUnixNano": str(end + 2_000_000),
            "status": {"code": 2 if error else 1},
            "attributes": [
                {"key": "http.route", "value": {"stringValue": "/checkout"}},
            ],
        }
        post(otlp([client_span], "gateway"))
        post(otlp([parent], "checkout-api"))
        sent += 2
        time.sleep(0.01)

    print(f"emitted {sent} spans")
    target.shutdown()


if __name__ == "__main__":
    main()
