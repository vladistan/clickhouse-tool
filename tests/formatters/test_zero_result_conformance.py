"""Step 4.6: a zero-column, zero-row RowSet must not raise in any formatter,
and each formatter's empty-result shape matches its own contract."""

import json

import pytest

from clickhouse_tool.formatters.json import JsonFormatter
from clickhouse_tool.formatters.ndjson import NdjsonFormatter
from clickhouse_tool.formatters.table import TableFormatter
from clickhouse_tool.formatters.toon import ToonFormatter

pytestmark = pytest.mark.unit

ALL_FORMATTERS = [TableFormatter, JsonFormatter, NdjsonFormatter, ToonFormatter]


@pytest.mark.parametrize("formatter_cls", ALL_FORMATTERS)
def test_zero_column_zero_row_result_does_not_raise(formatter_cls, empty_rowset):
    formatter = formatter_cls()
    list(formatter.format(empty_rowset))  # no exception


def test_table_emits_no_rows_for_zero_result(empty_rowset):
    assert list(TableFormatter().format(empty_rowset)) == []


def test_json_emits_empty_array_for_zero_result(empty_rowset):
    (line,) = JsonFormatter().format(empty_rowset)
    assert json.loads(line) == []


def test_ndjson_emits_nothing_for_zero_result(empty_rowset):
    assert list(NdjsonFormatter().format(empty_rowset)) == []


def test_toon_emits_empty_document_for_zero_result(empty_rowset):
    (document,) = ToonFormatter().format(empty_rowset)
    assert document == "result[0]{}:\n"
