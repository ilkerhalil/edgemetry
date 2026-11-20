"""CLI behaviour: exit codes and the table it prints."""

from __future__ import annotations

import json
import time

from edgemetry.cli import main
from edgemetry.model import Span
from edgemetry.store import Store


def seed(db_path: str, spans: list[Span]) -> None:
    store = Store(db_path)
    store.insert(spans)
    store.close()


def span(span_id: str, duration_ms: int, peer: str = "payments:8443", **kw) -> Span:
    now = time.time_ns()
    values = {
        "trace_id": "t",
        "span_id": span_id,
        "parent_span_id": "",
        "service": "gateway",
        "name": "POST",
        "kind": "client",
        "start_ns": now,
        "end_ns": now + duration_ms * 1_000_000,
        "status": "ok",
        "peer": peer,
        "attrs": {},
    }
    values.update(kw)
    return Span(**values)


def test_query_prints_a_table(tmp_path, capsys) -> None:
    db = str(tmp_path / "cli.db")
    seed(db, [span("a", 200), span("b", 900)])

    code = main(["query", "--db", db, "--since", "600"])
    out = capsys.readouterr().out
    assert code == 0
    assert "gateway" in out
    assert "865" in out  # p95 of 200 ms and 900 ms, interpolated
    assert "p95" in out


def test_query_with_no_data_returns_error(tmp_path, capsys) -> None:
    db = str(tmp_path / "empty.db")
    Store(db).close()
    assert main(["query", "--db", db]) == 1
    assert "no spans" in capsys.readouterr().out


def test_verify_warns_about_missing_peer(tmp_path, capsys) -> None:
    db = str(tmp_path / "verify.db")
    seed(db, [span("a", 10, peer=""), span("b", 10, peer="")])

    code = main(["verify", "--db", db, "--since", "600"])
    out = capsys.readouterr().out
    assert code == 2
    assert "below 95%" in out


def test_verify_passes_on_full_coverage(tmp_path, capsys) -> None:
    db = str(tmp_path / "verify-ok.db")
    seed(db, [span("a", 10)])

    assert main(["verify", "--db", db, "--since", "600"]) == 0
    assert "above 95%" in capsys.readouterr().out


def test_trace_prints_json(tmp_path, capsys) -> None:
    db = str(tmp_path / "trace.db")
    seed(db, [span("root", 100, kind="server", trace_id="abc")])

    assert main(["trace", "abc", "--db", db]) == 0
    assert '"span_id": "root"' in capsys.readouterr().out


def test_query_json_format(tmp_path, capsys) -> None:
    db = str(tmp_path / "json.db")
    seed(db, [span("a", 120)])

    assert main(["query", "--db", db, "--since", "600", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["edges"][0]["service"] == "gateway"
    assert payload["edges"][0]["p50_ms"] == 120.0


def test_prune_dry_run_deletes_nothing(tmp_path, capsys) -> None:
    db = str(tmp_path / "dry.db")
    seed(db, [span("old", 10, start_ns=0, end_ns=10**6)])

    assert main(["prune", "--db", db, "--older-than", "1d", "--dry-run"]) == 0
    assert "would delete" in capsys.readouterr().out

    store = Store(db)
    try:
        assert store.count() == 1
    finally:
        store.close()


def test_prune_deletes_old_spans(tmp_path, capsys) -> None:
    db = str(tmp_path / "prune.db")
    seed(db, [span("old", 10, start_ns=0, end_ns=10**6)])

    assert main(["prune", "--db", db, "--older-than", "1h"]) == 0
    assert "deleted" in capsys.readouterr().out

    store = Store(db)
    try:
        assert store.count() == 0
    finally:
        store.close()
