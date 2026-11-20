"""HTTP surface: OTLP/JSON ingest plus two query endpoints.

Deliberately stdlib-only: the receiver must be droppable next to an existing
collector without adding a dependency tree. OTLP/protobuf is the next step;
OTLP/HTTP JSON is enough to receive real spans today.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .model import parse_otlp_json
from .store import Store


class Handler(BaseHTTPRequestHandler):
    store: Store
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path not in ("/v1/traces", "/ingest/spans"):
            self._send(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            self._send(400, {"error": f"invalid json: {exc}"})
            return
        spans = parse_otlp_json(payload)
        accepted = self.store.insert(spans)
        self._send(200, {"accepted": accepted})

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/health":
            self._send(200, {"status": "ok"})
            return
        if parsed.path == "/v1/edges":
            rows = self.store.edges(
                since_s=int(query.get("since", ["3600"])[0]),
                service=query.get("service", [None])[0],
                peer=query.get("peer", [None])[0],
                kind=query.get("kind", ["client"])[0],
                limit=int(query.get("limit", ["50"])[0]),
            )
            self._send(200, {"edges": rows})
            return
        if parsed.path.startswith("/v1/traces/"):
            trace_id = parsed.path.rsplit("/", 1)[-1]
            spans = self.store.trace(trace_id)
            if not spans:
                self._send(404, {"error": "trace not found"})
                return
            self._send(200, {"trace_id": trace_id, "spans": spans})
            return
        self._send(404, {"error": "not found"})


def serve(db_path: str, host: str = "127.0.0.1", port: int = 4318) -> None:
    handler = type("BoundHandler", (Handler,), {"store": Store(db_path)})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"spanlens listening on http://{host}:{port}  db={db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
