"""Tests for the JSON formatter."""

import datetime
import json

import pytest

from clickhouse_tool.formatters.json import JsonFormatter

pytestmark = pytest.mark.unit


def test_zero_row_result_emits_empty_array(empty_rowset):
    formatter = JsonFormatter()
    (line,) = formatter.format(empty_rowset)
    assert json.loads(line) == []


def test_nested_map_column_serializes_as_object_with_keys_preserved(make_rowset):
    rows = make_rowset(
        ["resource"],
        [({"service.name": "api", 'has"quote': "v"},)],
    )
    formatter = JsonFormatter()
    (line,) = formatter.format(rows)
    decoded = json.loads(line)
    assert decoded == [{"resource": {"service.name": "api", 'has"quote': "v"}}]


def test_body_value_is_never_truncated(make_rowset):
    huge = "x" * 10_000
    rows = make_rowset(["Body"], [(huge,)])
    formatter = JsonFormatter()
    (line,) = formatter.format(rows)
    assert json.loads(line) == [{"Body": huge}]


def test_null_value_serializes_as_json_null(make_rowset):
    rows = make_rowset(["v"], [(None,)])
    formatter = JsonFormatter()
    (line,) = formatter.format(rows)
    assert json.loads(line) == [{"v": None}]


def test_datetime_value_serializes_via_isoformat(make_rowset):
    ts = datetime.datetime(2026, 1, 2, 3, 4, 5)
    rows = make_rowset(["ts"], [(ts,)])
    formatter = JsonFormatter()
    (line,) = formatter.format(rows)
    assert json.loads(line) == [{"ts": "2026-01-02 03:04:05"}]


def test_list_valued_column_serializes_as_json_array(make_rowset):
    rows = make_rowset(["tags"], [(["a", "b"],)])
    formatter = JsonFormatter()
    (line,) = formatter.format(rows)
    assert json.loads(line) == [{"tags": ["a", "b"]}]


def test_streaming_flag_is_false():
    assert JsonFormatter.streaming is False


def test_format_stream_delegates_to_format_per_block(make_rowset):
    formatter = JsonFormatter()
    block = make_rowset(["n"], [("only",)])
    lines = list(formatter.format_stream(iter([block])))
    assert json.loads(lines[0]) == [{"n": "only"}]


def test_date_decimal_uuid_and_ip_values_serialise_as_strings() -> None:
    from datetime import date
    from decimal import Decimal
    from ipaddress import ip_address
    from uuid import UUID

    from clickhouse_tool.formatters.json import json_value

    assert json_value(date(2026, 11, 6)) == "2026-11-06"
    assert json_value(Decimal("1.50")) == "1.50"
    assert (
        json_value(UUID("12345678-1234-5678-1234-567812345678"))
        == "12345678-1234-5678-1234-567812345678"
    )
    assert json_value(ip_address("10.0.0.1")) == "10.0.0.1"
