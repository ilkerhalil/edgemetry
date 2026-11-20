"""HTTP surface: OTLP ingest plus the query endpoints.

Deliberately stdlib-only. The receiver has to be droppable next to an existing
collector without dragging in a web framework: one process, no ASGI server, no
dependency tree to keep patched.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .model import parse_otlp_json
from .otlp_proto import parse_otlp_protobuf, protobuf_available

PROTOBUF_TYPES = ("application/x-protobuf", "application/protobuf", "application/octet-stream")


class Handler(BaseHTTPRequestHandler):
    """Request handler bound to a store instance by :func:`make_server`."""

    store: Any
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        """Silence per-request logging; the collector already logs the exporter side."""

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in ("/v1/traces", "/ingest/spans"):
            self._send(404, {"error": "not found"})
            return

        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}"
        content_type = (self.headers.get("Content-Type") or "").lower()
        try:
            if any(kind in content_type for kind in PROTOBUF_TYPES):
                if not protobuf_available():
                    self._send(
                        415,
                        {"error": "protobuf ingest unavailable: pip install spanlens[otlp]"},
                    )
                    return
                spans = parse_otlp_protobuf(body)
            else:
                spans = parse_otlp_json(json.loads(body))
        except json.JSONDecodeError as exc:
            self._send(400, {"error": f"invalid json: {exc}"})
            return
        except Exception as exc:
            self._send(400, {"error": f"decode failed: {exc}"})
            return

        self._send(200, {"accepted": self.store.insert(spans)})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            self._send(200, {"status": "ok"})
            return

        if parsed.path == "/v1/edges":
            try:
                rows = self.store.edges(
                    since_s=int(query.get("since", ["3600"])[0]),
                    service=query.get("service", [None])[0],
                    peer=query.get("peer", [None])[0],
                    kind=query.get("kind", ["client"])[0],
                    limit=int(query.get("limit", ["50"])[0]),
                )
            except ValueError as exc:
                self._send(400, {"error": f"invalid query: {exc}"})
                return
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


def make_server(store: Any, host: str = "127.0.0.1", port: int = 4318) -> ThreadingHTTPServer:
    """Build a server without starting it — integration tests bind port 0."""
    handler = type("BoundHandler", (Handler,), {"store": store})
    return ThreadingHTTPServer((host, port), handler)


def serve(store: Any, host: str = "127.0.0.1", port: int = 4318) -> None:
    server = make_server(store, host, port)
    print(f"spanlens listening on http://{host}:{port}  store={type(store).__name__}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
