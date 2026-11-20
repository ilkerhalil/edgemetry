"""PostgreSQL backend — the scale path that actually runs on this hardware.

Same interface as `Store`. Percentiles are computed in the database
(`percentile_cont`) instead of pulling every duration into Python, which is the
whole reason to move off SQLite.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from typing import Any

import psycopg

from .model import Span, build_tree

SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id        TEXT NOT NULL,
    span_id         TEXT NOT NULL,
    parent_span_id  TEXT NOT NULL DEFAULT '',
    service         TEXT NOT NULL,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,
    start_ns        BIGINT NOT NULL,
    end_ns          BIGINT NOT NULL,
    duration_ns     BIGINT NOT NULL,
    status          TEXT NOT NULL,
    peer            TEXT NOT NULL DEFAULT '',
    attrs           JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at     BIGINT NOT NULL,
    PRIMARY KEY (span_id)
);
CREATE INDEX IF NOT EXISTS idx_spans_edge ON spans (kind, start_ns) INCLUDE (service, peer, duration_ns);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans (trace_id, start_ns);
"""

EDGES_SQL = """
SELECT service, peer, name,
       count(*)                                            AS count,
       round(100.0 * count(*) FILTER (WHERE status = 'error') / count(*), 2) AS error_rate,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY duration_ns)::numeric / 1e6, 2) AS p50_ms,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ns)::numeric / 1e6, 2) AS p95_ms,
       round(percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ns)::numeric / 1e6, 2) AS p99_ms,
       round(max(duration_ns)::numeric / 1e6, 2) AS max_ms
FROM spans
WHERE kind = %(kind)s AND start_ns >= %(cutoff)s
  AND (%(service)s::text IS NULL OR service = %(service)s)
  AND (%(peer)s::text IS NULL OR peer ILIKE '%%' || %(peer)s || '%%')
GROUP BY service, peer, name
ORDER BY p95_ms DESC
LIMIT %(limit)s
"""


class PostgresStore:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self.conn = psycopg.connect(dsn, autocommit=True)
        self.conn.execute(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def insert(self, spans: Iterable[Span]) -> int:
        rows = [
            (
                s.trace_id,
                s.span_id,
                s.parent_span_id,
                s.service,
                s.name,
                s.kind,
                s.start_ns,
                s.end_ns,
                s.duration_ns,
                s.status,
                s.peer,
                json.dumps(s.attrs, ensure_ascii=False),
                int(time.time()),
            )
            for s in spans
        ]
        if not rows:
            return 0
        # COPY is roughly an order of magnitude faster than per-row INSERT for
        # OTLP batches, which arrive in bursts of hundreds of spans.
        with (
            self.conn.cursor() as cur,
            cur.copy(
                "COPY spans (trace_id, span_id, parent_span_id, service, name, kind,"
                " start_ns, end_ns, duration_ns, status, peer, attrs, received_at)"
                " FROM STDIN"
            ) as copy,
        ):
            for row in rows:
                copy.write_row(row)
        return len(rows)

    def edges(
        self,
        since_s: int = 3600,
        service: str | None = None,
        peer: str | None = None,
        kind: str = "client",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                EDGES_SQL,
                {
                    "kind": kind,
                    "cutoff": int((time.time() - since_s) * 1e9),
                    "service": service,
                    "peer": peer,
                    "limit": limit,
                },
            )
            cols = [d.name for d in cur.description]
            rows = []
            for values in cur.fetchall():
                item = dict(zip(cols, values, strict=False))
                item["span"] = item.pop("name")
                rows.append(item)
            return rows

    def peer_coverage(self, since_s: int = 3600) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT service, count(*) AS total,"
                " count(*) FILTER (WHERE peer = '') AS missing"
                " FROM spans WHERE kind = 'client' AND start_ns >= %s"
                " GROUP BY service ORDER BY total DESC",
                (int((time.time() - since_s) * 1e9),),
            )
            rows = cur.fetchall()
        return [
            {
                "service": service,
                "client_spans": total,
                "missing_peer": missing,
                "coverage_pct": round(100 * (1 - missing / total), 1) if total else 0.0,
            }
            for service, total, missing in rows
        ]

    def trace(self, trace_id: str) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT span_id, parent_span_id, service, name, kind, peer,"
                " duration_ns, start_ns, status FROM spans"
                " WHERE trace_id = %s ORDER BY start_ns",
                (trace_id,),
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
        return build_tree(rows)
