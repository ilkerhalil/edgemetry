"""Command line: serve, query, summary."""

from __future__ import annotations

import argparse
import json

from .api import serve
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spanlens", description="Span-level latency store")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="start the OTLP receiver and query API")
    p_serve.add_argument("--db", default="spans.db")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=4318)

    p_query = sub.add_parser("query", help="latency per callee")
    p_query.add_argument("--db", default="spans.db")
    p_query.add_argument("--since", type=int, default=3600, help="seconds")
    p_query.add_argument("--service")
    p_query.add_argument("--peer")
    p_query.add_argument("--kind", default="client")
    p_query.add_argument("--limit", type=int, default=20)

    p_trace = sub.add_parser("trace", help="waterfall for one trace id")
    p_trace.add_argument("trace_id")
    p_trace.add_argument("--db", default="spans.db")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        serve(args.db, args.host, args.port)
        return 0

    store = Store(args.db)
    try:
        if args.cmd == "query":
            rows = store.edges(args.since, args.service, args.peer, args.kind, args.limit)
            if not rows:
                print("no spans in window")
                return 1
            header = f"{'service':<18}{'peer':<26}{'span':<22}{'n':>6}{'p50':>8}{'p95':>8}{'p99':>8}{'err%':>7}"
            print(header)
            print("-" * len(header))
            for r in rows:
                print(
                    f"{r['service'][:17]:<18}{r['peer'][:25]:<26}{r['span'][:21]:<22}"
                    f"{r['count']:>6}{r['p50_ms']:>8.2f}{r['p95_ms']:>8.2f}"
                    f"{r['p99_ms']:>8.2f}{r['error_rate']:>7.1f}"
                )
            return 0
        print(json.dumps(store.trace(args.trace_id), indent=2, ensure_ascii=False))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
