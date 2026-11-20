"""Command line: serve, query, verify, trace, prune."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time

from .api import serve
from .store import Store

DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> int:
    """'7d' -> 604800. Bare numbers are seconds."""
    text = text.strip().lower()
    if not text:
        raise ValueError("empty duration")
    if text[-1] in DURATION_UNITS:
        return int(float(text[:-1]) * DURATION_UNITS[text[-1]])
    return int(float(text))


def retention_loop(store, window_s: int, interval_s: int = 21600) -> None:
    """Prune on a schedule so the table does not grow without bound."""
    while True:
        try:
            removed = store.prune(window_s)
            print(f"retention: removed {removed} spans older than {window_s}s", flush=True)
        except Exception as exc:
            print(f"retention failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(interval_s)


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
    parser = argparse.ArgumentParser(prog="edgemetry", description="Span-level latency store")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="start the OTLP receiver and query API")
    add_store_args(p_serve)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=4318)
    p_serve.add_argument(
        "--token",
        default=os.environ.get("EDGEMETRY_TOKEN"),
        help="bearer token for ingest and queries; defaults to $EDGEMETRY_TOKEN",
    )
    p_serve.add_argument(
        "--retention",
        help="delete spans older than this window, e.g. 7d or 48h; default: keep forever",
    )

    p_query = sub.add_parser("query", help="latency per callee")
    add_store_args(p_query)
    p_query.add_argument("--since", type=int, default=3600, help="seconds")
    p_query.add_argument("--service")
    p_query.add_argument("--peer")
    p_query.add_argument("--kind", default="client")
    p_query.add_argument("--limit", type=int, default=20)
    p_query.add_argument("--format", choices=["table", "json"], default="table")

    p_verify = sub.add_parser("verify", help="check that client spans carry a callee identifier")
    add_store_args(p_verify)
    p_verify.add_argument("--since", type=int, default=3600)

    p_trace = sub.add_parser("trace", help="waterfall for one trace id")
    add_store_args(p_trace)
    p_trace.add_argument("trace_id")

    p_prune = sub.add_parser("prune", help="delete spans older than a window")
    add_store_args(p_prune)
    p_prune.add_argument("--older-than", required=True, help="e.g. 7d, 48h, 3600")
    p_prune.add_argument("--dry-run", action="store_true", help="report without deleting")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        store = make_store(args)
        if args.retention:
            threading.Thread(
                target=retention_loop,
                args=(store, parse_duration(args.retention)),
                daemon=True,
            ).start()
        print(f"backend={args.backend}")
        serve(store, args.host, args.port, args.token)
        return 0

    store = make_store(args)
    try:
        if args.cmd == "prune":
            window = parse_duration(args.older_than)
            if args.dry_run:
                print(f"would delete spans older than {window}s ({args.older_than})")
                return 0
            removed = store.prune(window)
            print(f"deleted {removed} spans older than {window}s ({args.older_than})")
            return 0

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
            if args.format == "json":
                print(json.dumps({"edges": rows}, indent=2, ensure_ascii=False))
                return 0
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
