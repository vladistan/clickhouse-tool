"""Tests for the time-range parser."""

import pytest

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.query.timerange import (
    default_bucket_size,
    default_time_precision,
    parse_time_range,
    window_seconds,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "window,expected",
    [
        ("30s", (30, "SECOND")),
        ("5m", (5, "MINUTE")),
        ("15m", (15, "MINUTE")),
        ("1h", (1, "HOUR")),
        ("8h", (8, "HOUR")),
        ("24h", (24, "HOUR")),
        ("7d", (7, "DAY")),
        ("2w", (2, "WEEK")),
        ("1M", (1, "MONTH")),
    ],
)
def test_every_time_range_unit_parses(window: str, expected: tuple[int, str]) -> None:
    assert parse_time_range(window) == expected


@pytest.mark.parametrize("window", ["15x", "abc", "", "15", "m15"])
def test_unrecognised_unit_is_rejected(window: str) -> None:
    with pytest.raises(ConfigError):
        parse_time_range(window)


def test_parsed_unit_is_a_literal_never_a_placeholder() -> None:
    _, unit = parse_time_range("15m")
    assert unit == "MINUTE"
    assert "%" not in unit


@pytest.mark.parametrize(
    "window,expected",
    [("30s", 30), ("5m", 300), ("2h", 7200), ("1d", 86400)],
)
def test_window_seconds_converts_every_unit(window: str, expected: int) -> None:
    assert window_seconds(window) == expected


@pytest.mark.parametrize(
    "window,expected_bucket",
    [
        ("24h", "1h"),
        ("1h", "5m"),
        ("150s", "5s"),
        ("3m", "5s"),
    ],
)
def test_default_bucket_size_snaps_to_a_nice_width(window: str, expected_bucket: str) -> None:
    assert default_bucket_size(window) == expected_bucket


def test_default_bucket_size_caps_at_the_largest_candidate_for_huge_windows() -> None:
    assert default_bucket_size("52w") == "7d"


@pytest.mark.parametrize(
    "window,expected",
    [("15m", "s"), ("1h", "s"), ("2h", "s"), ("3h", "m"), ("24h", "m"), ("7d", "m")],
)
def test_default_time_precision_drops_to_minutes_past_three_hours(window: str, expected: str) -> None:
    assert default_time_precision(window) == expected
