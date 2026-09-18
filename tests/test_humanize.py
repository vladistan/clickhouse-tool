"""Tests for the 'last seen' relative-time formatter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from clickhouse_tool.core.humanize import format_relative_time, humanize_number

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=0), "0s ago"),
        (timedelta(seconds=3), "3s ago"),
        (timedelta(minutes=5, seconds=3), "5m ago"),
        (timedelta(minutes=5, seconds=30), "5m 30s ago"),
        (timedelta(hours=1, minutes=3), "1h ago"),
        (timedelta(hours=2, minutes=20), "2h 20m ago"),
        (timedelta(days=2, hours=4), "2d ago"),
        (timedelta(days=2, hours=10), "2d 10h ago"),
    ],
)
def test_secondary_unit_shown_only_at_or_above_ten(delta: timedelta, expected: str) -> None:
    assert format_relative_time(_NOW - delta, now=_NOW) == expected


def test_naive_datetime_is_treated_as_utc() -> None:
    naive = (_NOW - timedelta(minutes=5)).replace(tzinfo=None)
    assert format_relative_time(naive, now=_NOW) == "5m ago"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1024, "1024"),
        (9999, "9999"),
        (10000, "10k"),
        (12345, "12.35k"),
        (1_000_000, "1000k"),
        (10_000_000, "10m"),
        (10_000_000_000, "10g"),
        (0.123456, "0.12"),
        (0, "0"),
        (-10000, "-10k"),
        (-0.001, "0"),
    ],
)
def test_humanize_number_suffixes_only_once_scaled_value_hits_ten(value: float, expected: str) -> None:
    assert humanize_number(value) == expected


def test_humanize_number_honours_a_decimals_override() -> None:
    assert humanize_number(12345, decimals=0) == "12k"
    assert humanize_number(0.123456, decimals=4) == "0.1235"
