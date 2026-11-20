"""Scale check: how the two backends behave as span volume grows.

Generates synthetic client spans with a known distribution, inserts them, and
times the same aggregate query. Not a benchmark suite — one honest data point.
"""

from __future__ import annotations

import random
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from spanlens.model import Span  # noqa: E402
from spanlens.store import Store  # noqa: E402
from spanlens.store_pg import PostgresStore  # noqa: E402

N = 100_000
PEERS = [f"svc{i}.internal:8443" for i in range(8)]
random.seed(11)
now = time.time_ns()

SPANS = [
    Span(
        trace_id=f"{i:032x}", span_id=f"{i:016x}", parent_span_id="",
        service=f"gateway{i % 4}", name="POST",
        kind="client", start_ns=now - (i % 3600) * 10**9,
        end_ns=now - (i % 3600) * 10**9 + int(random.gauss(200, 40) * 1e6),
        status="error" if i % 20 == 0 else "ok",
        peer=PEERS[i % len(PEERS)], attrs={},
    )
    for i in range(N)
]


def run(label: str, store, repeats: int = 3) -> None:
    t0 = time.perf_counter()
    inserted = store.insert(SPANS)
    insert_s = time.perf_counter() - t0
    times = []
    for _ in range(repeats):
        t = time.perf_counter()
        rows = store.edges(since_s=7200, limit=20)
        times.append((time.perf_counter() - t) * 1000)
    print(f"{label:<10} {inserted:>7} span  yazma {insert_s:6.2f}s  "
          f"sorgu medyan {statistics.median(times):7.1f} ms  "
          f"(min {min(times):.1f} / maks {max(times):.1f})  kenar={len(rows)}")


if __name__ == "__main__":
    backend = sys.argv[1] if len(sys.argv) > 1 else "sqlite"
    if backend == "sqlite":
        db = Path("/tmp/scale.db")
        for suffix in ("", "-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
        run("sqlite", Store(db))
    else:
        run("postgres", PostgresStore(
            "postgresql://postgres:spanlens@127.0.0.1:5434/spanlens_scale"))
