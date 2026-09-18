"""Tests for column mapping and validation."""

import pytest

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.query.columns import COLUMN_MAP, DEFAULT_LOG_COLS, validate_columns

pytestmark = pytest.mark.unit


def test_default_column_set_is_exactly_five_columns() -> None:
    assert DEFAULT_LOG_COLS == ("ts", "level", "host", "service", "msg")


def test_id_is_available_but_not_default() -> None:
    assert "id" in COLUMN_MAP
    assert "id" not in DEFAULT_LOG_COLS


def test_id_maps_to_a_synthetic_per_row_hash_not_trace_id() -> None:
    """TraceId is empty on most live rows: not a usable row identifier.
    `id` maps to a deterministic hash over per-row-varying columns
    instead."""
    assert COLUMN_MAP["id"] == "hex(cityHash64(Timestamp, ServiceName, HostName, Body))"


def test_validate_columns_accepts_known_names() -> None:
    assert validate_columns(("ts", "level")) == ("ts", "level")


def test_validate_columns_rejects_unknown_name_listing_accepted_names() -> None:
    with pytest.raises(ConfigError) as exc_info:
        validate_columns(("ts", "bogus"))

    assert "bogus" in str(exc_info.value)
    for name in COLUMN_MAP:
        assert name in str(exc_info.value)
