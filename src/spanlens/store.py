"""SQLite storage and aggregation.

v0.1 keeps spans in SQLite: one process, no dependencies. The schema and the
aggregation functions are the parts that survive a move to ClickHouse; only
`Store` changes.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .model import Span

SCHEMA = """
CREATE TABLE IF NOT EXISTS spans (
    trace_id      TEXT NOT NULL,
    span_id       TEXT PRIMARY KEY,
    parent_span_id TEXT NOT NULL DEFAULT '',
    service       TEXT NOT NULL,
    name          TEXT NOT NULL,
    kind          TEXT NOT NULL,
    start_ns      INTEGER NOT NULL,
    end_ns        INTEGER NOT NULL,
    duration_ns   INTEGER NOT NULL,
    status        TEXT NOT NULL,
    peer          TEXT NOT NULL DEFAULT '',
    attrs         TEXT NOT NULL DEFAULT '{}',
    received_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_edge ON spans(kind, peer, start_ns);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS idx_spans_service ON spans(service, start_ns);
"""


def percentile(values: list[int], q: float) -> float:
    """Nearest-rank percentile; q in [0, 100]. Returns 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (q / 100) * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    frac = rank - low
    return ordered[low] + (ordered[high] - ordered[low]) * frac


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def insert(self, spans: Iterable[Span]) -> int:
        now = int(time.time())
        rows = [
            (
                s.trace_id, s.span_id, s.parent_span_id, s.service, s.name, s.kind,
                s.start_ns, s.end_ns, s.duration_ns, s.status, s.peer,
                json.dumps(s.attrs, ensure_ascii=False), now,
            )
            for s in spans
        ]
        if not rows:
            return 0
        self.conn.executemany(
            "INSERT OR REPLACE INTO spans (trace_id, span_id, parent_span_id, service, name,"
            " kind, start_ns, end_ns, duration_ns, status, peer, attrs, received_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def edges(
        self,
        since_s: int = 3600,
        service: str | None = None,
        peer: str | None = None,
        kind: str = "client",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Latency per (caller service, callee peer, span name).

        Answers "how slow are our outbound calls" — the aggregate path, not the
        single-trace waterfall.
        """
        cutoff = (time.time() - since_s) * 1e9
        sql = [
            "SELECT service, peer, name, duration_ns, status FROM spans",
            "WHERE kind = ? AND start_ns >= ?",
        ]
        args: list[Any] = [kind, int(cutoff)]
        if service:
            sql.append("AND service = ?")
            args.append(service)
        if peer:
            sql.append("AND peer LIKE ?")
            args.append(f"%{peer}%")
        sql.append("ORDER BY start_ns DESC LIMIT 200000")

        buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in self.conn.execute(" ".join(sql), args):
            key = (row["service"], row["peer"], row["name"])
            b = buckets.setdefault(key, {"durations": [], "errors": 0, "total": 0})
            b["durations"].append(row["duration_ns"])
            b["total"] += 1
            if row["status"] == "error":
                b["errors"] += 1

        out = []
        for (svc, pr, name), b in buckets.items():
            durations = b["durations"]
            total = b["total"]
            out.append({
                "service": svc,
                "peer": pr,
                "span": name,
                "count": total,
                "error_rate": round(b["errors"] / total * 100, 2) if total else 0.0,
                "p50_ms": round(percentile(durations, 50) / 1e6, 2),
                "p95_ms": round(percentile(durations, 95) / 1e6, 2),
                "p99_ms": round(percentile(durations, 99) / 1e6, 2),
                "max_ms": round(max(durations) / 1e6, 2),
            })
        out.sort(key=lambda r: r["p95_ms"], reverse=True)
        return out[:limit]

    def trace(self, trace_id: str) -> list[dict[str, Any]]:
        rows = list(self.conn.execute(
            "SELECT * FROM spans WHERE trace_id = ? ORDER BY start_ns", (trace_id,)
        ))
        children: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            children.setdefault(row["parent_span_id"], []).append(row)

        def build(row: sqlite3.Row) -> dict[str, Any]:
            kids = [build(k) for k in children.get(row["span_id"], [])]
            child_ns = sum(k["duration_ns"] for k in kids)
            return {
                "span_id": row["span_id"],
                "parent_span_id": row["parent_span_id"],
                "service": row["service"],
                "name": row["name"],
                "kind": row["kind"],
                "peer": row["peer"],
                "duration_ns": row["duration_ns"],
                "start_ns": row["start_ns"],
                "self_ns": max(row["duration_ns"] - child_ns, 0),
                "status": row["status"],
                "children": kids,
            }

        return [build(r) for r in children.get("", [])]
