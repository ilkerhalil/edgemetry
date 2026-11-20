"""Retention: duration parsing and the delete itself."""

from __future__ import annotations

import time

import pytest

from edgemetry.cli import parse_duration


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30s", 30),
        ("5m", 300),
        ("2h", 7200),
        ("7d", 604800),
        ("3600", 3600),
        (" 1D ", 86400),
        ("0.5h", 1800),
    ],
)
def test_parse_duration(text: str, expected: int) -> None:
    assert parse_duration(text) == expected


def test_parse_duration_rejects_empty() -> None:
    with pytest.raises(ValueError):
        parse_duration("   ")


def test_prune_removes_only_old_spans(store, make_span) -> None:
    now = time.time_ns()
    store.insert(
        [
            make_span(
                span_id="old",
                start_ns=now - 10 * 86400 * 10**9,
                end_ns=now - 10 * 86400 * 10**9 + 10**6,
            ),
            make_span(span_id="new", start_ns=now, end_ns=now + 10**6),
        ]
    )
    assert store.count() == 2

    removed = store.prune(older_than_s=7 * 86400)
    assert removed == 1
    assert store.count() == 1
    assert store.trace("t1")[0]["span_id"] == "new"


def test_prune_on_empty_store_returns_zero(store) -> None:
    assert store.prune(older_than_s=60) == 0


def test_ping_reports_healthy_store(store) -> None:
    assert store.ping() is True


def test_ping_reports_closed_store_as_down(store) -> None:
    store.close()
    assert store.ping() is False
