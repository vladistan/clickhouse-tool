"""Tests for the hand-rolled TOON encoder."""

import re

import pytest

from clickhouse_tool.formatters.toon import ToonFormatter, encode, render_field

pytestmark = pytest.mark.unit

_HEADER_RE = re.compile(r"^result\[(\d+)\]\{[^}]*\}:$")


def _declared_count(document: str) -> int:
    header = document.splitlines()[0]
    match = _HEADER_RE.match(header)
    assert match is not None, f"header did not match dialect: {header!r}"
    return int(match.group(1))


def test_matches_invoice_tool_dialect_header_and_indent(make_rowset):
    rows = make_rowset(["month", "customer"], [("2026-01", "acme")])
    document = encode(rows)
    lines = document.splitlines()
    assert lines[0] == "result[1]{month,customer}:"
    assert lines[1] == "  2026-01,acme"


def test_declared_header_count_equals_emitted_row_count():
    for row_count in (0, 1, 2, 5, 37):
        columns = ["a", "b"]
        rows_data = [(f"v{i}a", f"v{i}b") for i in range(row_count)]
        from clickhouse_tool.core.models import ColumnMeta, RowSet

        rowset = RowSet(
            columns=tuple(ColumnMeta(name=c, ch_type="String") for c in columns),
            rows=tuple(rows_data),
            row_count=row_count,
        )
        document = encode(rowset)
        body_lines = [line for line in document.splitlines()[1:] if line]
        assert _declared_count(document) == len(body_lines) == row_count


def test_zero_row_result_emits_empty_document_with_zero_count(empty_rowset):
    document = encode(empty_rowset)
    assert document == "result[0]{}:\n"


def test_encoding_is_deterministic(make_rowset):
    rows = make_rowset(["a"], [("x",), ("y",)])
    assert encode(rows) == encode(rows)


def test_document_is_lf_terminated(make_rowset):
    rows = make_rowset(["a"], [("x",)])
    assert encode(rows).endswith("\n")
    assert "\r" not in encode(rows)


def test_none_renders_as_dash():
    assert render_field(None) == "-"


def test_plain_field_is_unquoted():
    assert render_field("hello") == "hello"


def test_datetime_renders_via_isoformat():
    import datetime

    value = datetime.datetime(2026, 1, 2, 3, 4, 5)
    assert render_field(value) == "2026-01-02 03:04:05"


def test_streaming_flag_is_false():
    assert ToonFormatter.streaming is False


def test_format_stream_delegates_to_format_per_block(make_rowset):
    formatter = ToonFormatter()
    block = make_rowset(["n"], [("only",)])
    (document,) = list(formatter.format_stream(iter([block])))
    assert "only" in document
