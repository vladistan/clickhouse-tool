"""Tests for shared result and statement data models."""

import pytest

from clickhouse_tool.core.models import ColumnMeta, QueryStats, RowSet, SqlStatement

pytestmark = pytest.mark.unit


def test_column_meta_carries_name_and_type() -> None:
    # ColumnMeta holds one column's name and ClickHouse type.
    col = ColumnMeta(name="HostName", ch_type="String")
    assert col.name == "HostName"
    assert col.ch_type == "String"


def test_rowset_reports_row_count_and_truncated_for_empty_result() -> None:
    rowset = RowSet(columns=(), rows=(), row_count=0, truncated=False)
    assert rowset.row_count == 0
    assert rowset.truncated is False


def test_rowset_zero_column_shape() -> None:
    rowset = RowSet(columns=(), rows=((),), row_count=1, truncated=False)
    assert rowset.columns == ()
    assert rowset.row_count == 1


def test_sql_statement_keeps_sql_and_params_separate() -> None:
    stmt = SqlStatement(sql="SELECT 1", params={"a": 1})
    assert stmt.sql == "SELECT 1"
    assert stmt.params == {"a": 1}


def test_sql_statement_meta_never_affects_equality() -> None:
    a = SqlStatement(sql="SELECT 1", params={"a": 1}, meta={"strategy": "token"})
    b = SqlStatement(sql="SELECT 1", params={"a": 1}, meta={"strategy": "ilike"})
    assert a == b


def test_sql_statement_differing_params_are_not_equal() -> None:
    a = SqlStatement(sql="SELECT 1", params={"a": 1})
    b = SqlStatement(sql="SELECT 1", params={"a": 2})
    assert a != b


def test_query_stats_fields() -> None:
    stats = QueryStats(elapsed=0.5, rows_read=100, bytes_read=2048)
    assert stats.elapsed == 0.5
    assert stats.rows_read == 100
    assert stats.bytes_read == 2048
