"""Percentile arithmetic — the number every query result depends on."""

from __future__ import annotations

import pytest

from spanlens.store import percentile


def test_empty_returns_zero() -> None:
    assert percentile([], 95) == 0.0


def test_single_value() -> None:
    assert percentile([7], 99) == 7.0


def test_median_of_odd_sample() -> None:
    assert percentile([10, 20, 30, 40, 50], 50) == 30


def test_high_percentile_interpolates_between_neighbours() -> None:
    assert percentile([10, 20, 30, 40, 50], 95) == pytest.approx(48.0)


def test_p100_is_maximum() -> None:
    assert percentile([3, 1, 9], 100) == 9


def test_unsorted_input_is_sorted_first() -> None:
    assert percentile([50, 10, 30], 50) == 30.0


def test_nanosecond_durations_keep_precision() -> None:
    values = [int(200.5e6), int(900.25e6)]
    assert percentile(values, 50) == pytest.approx(550_375_000.0)
