"""Tests for the NDJSON formatter."""

import json

import pytest

from clickhouse_tool.formatters.ndjson import NdjsonFormatter

pytestmark = pytest.mark.unit


def test_declares_itself_streaming():
    assert NdjsonFormatter.streaming is True


def test_emits_one_line_per_row_as_it_arrives(make_rowset):
    rows = make_rowset(["n"], [("first",), ("second",)])
    formatter = NdjsonFormatter()
    lines = list(formatter.format(rows))
    assert [json.loads(line) for line in lines] == [{"n": "first"}, {"n": "second"}]


def test_zero_row_result_emits_nothing(empty_rowset):
    formatter = NdjsonFormatter()
    assert list(formatter.format(empty_rowset)) == []


def test_format_holds_no_buffer_it_yields_lazily(make_rowset):
    rows = make_rowset(["n"], [("a",), ("b",), ("c",)])
    formatter = NdjsonFormatter()
    gen = formatter.format(rows)
    first = next(gen)
    assert json.loads(first) == {"n": "a"}
    # Abandoning the generator part-way (a closed pipe downstream) must not raise.
    gen.close()


def test_format_stream_emits_row_by_row_across_blocks(make_rowset):
    block_a = make_rowset(["n"], [("a",)])
    block_b = make_rowset(["n"], [("b",)])
    formatter = NdjsonFormatter()
    lines = list(formatter.format_stream(iter([block_a, block_b])))
    assert [json.loads(line) for line in lines] == [{"n": "a"}, {"n": "b"}]


def test_format_stream_of_empty_blocks_emits_nothing(empty_rowset):
    formatter = NdjsonFormatter()
    assert list(formatter.format_stream(iter([empty_rowset, empty_rowset]))) == []
