"""Command line: serve, query, trace."""

from __future__ import annotations

import argparse
import json

from .api import serve
from .store import Store


def make_store(args):
    if getattr(args, "backend", "sqlite") == "postgres":
        from .store_pg import PostgresStore

        if not args.dsn:
            raise SystemExit("--dsn is required for the postgres backend")
        return PostgresStore(args.dsn)
    return Store(args.db)


def add_store_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", choices=["sqlite", "postgres"], default="sqlite")
    parser.add_argument("--db", default="spans.db", help="sqlite file")
    parser.add_argument("--dsn", help="postgres dsn, e.g. postgresql://user:pass@host/db")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="spanlens", description="Span-level latency store")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="start the OTLP receiver and query API")
    add_store_args(p_serve)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=4318)

    p_query = sub.add_parser("query", help="latency per callee")
    add_store_args(p_query)
    p_query.add_argument("--since", type=int, default=3600, help="seconds")
    p_query.add_argument("--service")
    p_query.add_argument("--peer")
    p_query.add_argument("--kind", default="client")
    p_query.add_argument("--limit", type=int, default=20)

    p_verify = sub.add_parser("verify", help="check that client spans carry a callee identifier")
    add_store_args(p_verify)
    p_verify.add_argument("--since", type=int, default=3600)

    p_trace = sub.add_parser("trace", help="waterfall for one trace id")
    add_store_args(p_trace)
    p_trace.add_argument("trace_id")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        store = make_store(args)
        print(f"backend={args.backend}")
        serve(store, args.host, args.port)
        return 0

    store = make_store(args)
    try:
        if args.cmd == "verify":
            rows = store.peer_coverage(args.since)
            if not rows:
                print("no client spans in window — is the collector exporting?")
                return 1
            print(f"{'service':<24}{'client spans':>14}{'missing peer':>14}{'coverage':>11}")
            print("-" * 63)
            bad = 0
            for r in rows:
                if r["coverage_pct"] < 95:
                    bad += 1
                print(
                    f"{r['service'][:23]:<24}{r['client_spans']:>14}"
                    f"{r['missing_peer']:>14}{r['coverage_pct']:>10.1f}%"
                )
            print()
            if bad:
                print(
                    f"{bad} service(s) below 95% coverage: no callee on the span, "
                    "so per-endpoint latency cannot be computed"
                )
                return 2
            print("all services above 95% coverage")
            return 0

        if args.cmd == "query":
            rows = store.edges(args.since, args.service, args.peer, args.kind, args.limit)
            if not rows:
                print("no spans in window")
                return 1
            header = (
                f"{'service':<18}{'peer':<26}{'span':<22}"
                f"{'n':>6}{'p50':>8}{'p95':>8}{'p99':>8}{'err%':>7}"
            )
            print(header)
            print("-" * len(header))
            for r in rows:
                print(
                    f"{r['service'][:17]:<18}{r['peer'][:25]:<26}{r['span'][:21]:<22}"
                    f"{r['count']:>6}{float(r['p50_ms'] or 0):>8.2f}"
                    f"{float(r['p95_ms'] or 0):>8.2f}{float(r['p99_ms'] or 0):>8.2f}"
                    f"{float(r['error_rate'] or 0):>7.1f}"
                )
            return 0
        print(json.dumps(store.trace(args.trace_id), indent=2, ensure_ascii=False))
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
