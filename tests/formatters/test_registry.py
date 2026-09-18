"""Tests for import-time formatter registration and name resolution."""

from __future__ import annotations

import pytest

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.formatters import get_formatter, registry
from clickhouse_tool.formatters.json import JsonFormatter
from clickhouse_tool.formatters.ndjson import NdjsonFormatter
from clickhouse_tool.formatters.table import TableFormatter
from clickhouse_tool.formatters.toon import ToonFormatter

pytestmark = pytest.mark.unit


def test_importing_the_package_resolves_all_four_names() -> None:
    assert registry.names() == ("json", "ndjson", "table", "toon")


def test_get_formatter_returns_the_correct_instance() -> None:
    assert isinstance(get_formatter("json"), JsonFormatter)
    assert isinstance(get_formatter("ndjson"), NdjsonFormatter)
    assert isinstance(get_formatter("table"), TableFormatter)
    assert isinstance(get_formatter("toon"), ToonFormatter)


def test_unknown_format_name_raises_config_error_listing_registered_names() -> None:
    with pytest.raises(ConfigError, match=r"json.*ndjson.*table.*toon"):
        get_formatter("csv")
