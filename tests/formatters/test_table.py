"""Tests for the table formatter."""

from datetime import datetime

import pytest

from clickhouse_tool.formatters.table import (
    TableFormatter,
    _fixed_column_widths,
    _measure_natural_widths,
    _render_cell,
)

pytestmark = pytest.mark.unit


def test_none_renders_as_dash_not_the_string_none():
    assert _render_cell(None) == "-"


def test_int_and_float_cells_are_humanized():
    assert _render_cell(10000) == "10k"
    assert _render_cell(0.123456) == "0.12"


def test_bool_cells_are_not_humanized_as_numbers():
    assert _render_cell(True) == "True"
    assert _render_cell(False) == "False"


def test_timestamp_defaults_to_whole_seconds():
    assert _render_cell(datetime(2026, 1, 1, 12, 30, 45, 123456)) == "2026-01-01 12:30:45"


def test_timestamp_ts_decimals_adds_a_fraction():
    assert _render_cell(datetime(2026, 1, 1, 12, 30, 45, 123456), ts_decimals=3) == "2026-01-01 12:30:45.123"


def test_timestamp_minute_precision_drops_seconds():
    assert (
        _render_cell(datetime(2026, 1, 1, 12, 30, 45, 123456), ts_precision="m") == "2026-01-01 12:30"
    )


def test_large_value_is_truncated_with_marker():
    huge = "x" * 1000
    rendered = _render_cell(huge)
    assert rendered.endswith("... [truncated]")
    assert len(rendered) < len(huge)


def test_small_value_is_not_truncated():
    assert _render_cell("hello") == "hello"


def test_zero_column_result_emits_no_rows(empty_rowset):
    formatter = TableFormatter()
    lines = list(formatter.format(empty_rowset))
    assert lines == []


def test_column_order_matches_source_rowset(make_rowset):
    rows = make_rowset(["host", "level", "msg"], [("a", "info", "hi")])
    formatter = TableFormatter()
    output = "\n".join(formatter.format(rows))
    host_idx = output.index("host")
    level_idx = output.index("level")
    msg_idx = output.index("msg")
    assert host_idx < level_idx < msg_idx


def test_row_order_matches_source_rowset(make_rowset):
    rows = make_rowset(["n"], [("first",), ("second",), ("third",)])
    formatter = TableFormatter()
    output = "\n".join(formatter.format(rows))
    first_idx = output.index("first")
    second_idx = output.index("second")
    third_idx = output.index("third")
    assert first_idx < second_idx < third_idx


def test_format_stream_delegates_to_format_per_block(make_rowset):
    formatter = TableFormatter()
    block = make_rowset(["n"], [("only",)])
    lines = list(formatter.format_stream(iter([block])))
    assert any("only" in line for line in lines)


def test_streaming_flag_is_false():
    assert TableFormatter.streaming is False


def test_measure_natural_widths_takes_the_wider_of_header_or_content():
    widths = _measure_natural_widths(["service", "msg"], [("api", "a short message here")])
    assert widths["service"] == len("service")
    assert widths["msg"] == len("a short message here")


def test_measure_natural_widths_floors_at_the_minimum():
    widths = _measure_natural_widths(["n"], [("x",)])
    assert widths["n"] >= 6  # _MIN_COL_WIDTH


def test_fixed_column_widths_keeps_columns_distinct_not_evenly_split():
    widths = _fixed_column_widths(["level", "msg"], [("info", "a fairly long message")], total_width=200)
    assert widths["level"] < widths["msg"]


def test_fixed_column_widths_shrinks_only_the_widest_column_to_fit():
    rows = [("api", "x" * 100)]
    widths = _fixed_column_widths(["service", "msg"], rows, total_width=20)
    assert widths["service"] == len("service")  # untouched, still its natural width
    assert widths["msg"] < 100  # the overflow came out of msg alone


def test_follow_mode_suppresses_the_header(make_rowset):
    rows = make_rowset(["host"], [("h1",)])
    formatter = TableFormatter(follow=True)
    output = "\n".join(formatter.format(rows))
    assert "host" not in output


def test_non_follow_mode_still_shows_the_header(make_rowset):
    rows = make_rowset(["host"], [("h1",)])
    formatter = TableFormatter()
    output = "\n".join(formatter.format(rows))
    assert "host" in output


def test_follow_mode_suppresses_the_top_and_bottom_border(make_rowset):
    rows = make_rowset(["host"], [("h1",)])
    formatter = TableFormatter(follow=True)
    output = "\n".join(formatter.format(rows))
    assert "┏" not in output
    assert "└" not in output


def test_non_follow_mode_still_shows_the_border(make_rowset):
    rows = make_rowset(["host"], [("h1",)])
    formatter = TableFormatter()
    output = "\n".join(formatter.format(rows))
    assert "┏" in output
    assert "└" in output


def test_follow_mode_freezes_column_widths_across_batches(make_rowset):
    formatter = TableFormatter(follow=True)
    first = make_rowset(["msg"], [("short",)])
    list(formatter.format(first))
    frozen = formatter._column_widths
    assert frozen is not None

    second = make_rowset(["msg"], [("a much, much longer message than before",)])
    list(formatter.format(second))
    assert formatter._column_widths == frozen
