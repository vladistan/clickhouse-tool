"""Tests for the arrival-order cursor, the schema probe and lag classification."""

from __future__ import annotations

import json

import pytest

from clickhouse_tool.core.models import ColumnMeta, RowSet
from clickhouse_tool.core.schema import build_column_probe, probe_columns
from clickhouse_tool.formatters.json import JsonFormatter
from clickhouse_tool.formatters.ndjson import NdjsonFormatter
from clickhouse_tool.formatters.toon import ToonFormatter
from clickhouse_tool.query.builder import (
    ARRIVAL_CURSOR_COLUMN,
    CURSOR_COLUMN,
    build_arrival_start_cursor,
    build_logs,
    build_logs_since,
    build_logs_since_arrival,
)
from clickhouse_tool.query.columns import LAG_COLUMN, apply_lag_column, classify_lag
from clickhouse_tool.query.intents import Filters, LogsIntent

pytestmark = pytest.mark.unit


def test_column_probe_targets_the_qualified_table() -> None:
    statement = build_column_probe("otel.otel_logs")
    assert "system.columns" in statement.sql
    assert statement.params == {"db": "otel", "tbl": "otel_logs"}


def test_probe_columns_runs_one_query_and_returns_names() -> None:
    class _Client:
        calls = 0

        def execute(self, statement: object) -> RowSet:
            _Client.calls += 1
            cols = (ColumnMeta(name="name", ch_type="String"),)
            return RowSet(columns=cols, rows=(("Timestamp",), ("InsertedAt",)), row_count=2)

    assert probe_columns(_Client(), "otel.otel_logs") == frozenset({"Timestamp", "InsertedAt"})  # type: ignore[arg-type]
    assert _Client.calls == 1


def test_arrival_poll_reads_completed_seconds_after_a_tuple_cursor() -> None:
    statement = build_logs_since_arrival(
        LogsIntent(filters=Filters(host="h1")),
        "otel.otel_logs",
        ("2026-11-06 21:00:00", "2026-11-06 20:59:58.123456789"),
    )
    assert (
        "(InsertedAt, Timestamp) > (toDateTime(%(since_ins)s), toDateTime64(%(since_ts)s, 9))"
        in statement.sql
    )
    assert "InsertedAt < now() - INTERVAL 2 SECOND" in statement.sql
    assert "toDate(Timestamp) >= today() - 1" in statement.sql
    assert statement.sql.endswith("ORDER BY InsertedAt ASC, Timestamp ASC LIMIT %(limit)s")
    assert statement.params["since_ins"] == "2026-11-06 21:00:00"
    assert statement.params["since_ts"] == "2026-11-06 20:59:58.123456789"
    assert "h1" not in statement.sql
    assert statement.meta["column_names"][-3:] == (LAG_COLUMN, ARRIVAL_CURSOR_COLUMN, CURSOR_COLUMN)


def test_arrival_poll_never_carries_a_time_range() -> None:
    statement = build_logs_since_arrival(
        LogsIntent(filters=Filters(time_range="15m")), "otel.otel_logs", ("a", "b")
    )
    assert "INTERVAL %(tr_count)s" not in statement.sql


def test_arrival_start_cursor_is_server_side_and_settled() -> None:
    statement = build_arrival_start_cursor()
    assert "now() - INTERVAL 2 SECOND" in statement.sql
    assert "1970-01-01 00:00:00.000000000" in statement.sql


def test_event_time_poll_is_unchanged_without_schema_knowledge() -> None:
    statement = build_logs_since(LogsIntent(), "otel.otel_logs", "2026-01-01 00:00:00")
    assert "Timestamp > %(since)s" in statement.sql
    assert LAG_COLUMN not in statement.sql


@pytest.mark.parametrize(
    ("has_inserted_at", "expected"),
    [
        (True, "dateDiff('second', Timestamp, InsertedAt)"),
        (False, "dateDiff('second', Timestamp, now())"),
    ],
    ids=["with-inserted-at", "without"],
)
def test_logs_projects_the_hidden_lag_column(has_inserted_at: bool, expected: str) -> None:
    statement = build_logs(LogsIntent(), "otel.otel_logs", has_inserted_at)
    assert f"{expected} AS {LAG_COLUMN}" in statement.sql
    assert statement.meta["column_names"][-1] == LAG_COLUMN


def test_full_projection_has_no_lag_column() -> None:
    statement = build_logs(LogsIntent(full=True), "otel.otel_logs", True)
    assert LAG_COLUMN not in statement.sql


@pytest.mark.parametrize(
    ("lag", "expected"),
    [(125, "late"), (124, None), (0, None), (-5, None), (-6, "future")],
)
def test_classify_lag_thresholds(lag: int, expected: str | None) -> None:
    assert classify_lag(lag, late_after_s=124, future_after_s=5) == expected


def test_classify_lag_honours_overridden_thresholds() -> None:
    assert classify_lag(31, late_after_s=30, future_after_s=5) == "late"
    assert classify_lag(-2, late_after_s=30, future_after_s=1) == "future"


def _rows_with_lag() -> RowSet:
    cols = (ColumnMeta(name="msg", ch_type="String"), ColumnMeta(name=LAG_COLUMN, ch_type="Int64"))
    return RowSet(columns=cols, rows=(("ok", 14), ("late", 237), ("early", -18000)), row_count=3)


def test_apply_lag_column_keeps_the_lag_on_flagged_rows_only() -> None:
    out = apply_lag_column(_rows_with_lag(), late_after_s=124, future_after_s=5)
    assert [c.name for c in out.columns] == ["msg", "lag_s"]
    assert out.rows == (("ok", None), ("late", 237), ("early", -18000))


def test_apply_lag_column_is_a_no_op_without_the_hidden_column() -> None:
    rows = RowSet(columns=(ColumnMeta(name="msg", ch_type="String"),), rows=(("x",),), row_count=1)
    assert apply_lag_column(rows, 124, 5) is rows


def test_json_carries_lag_s_on_flagged_rows_only() -> None:
    out = apply_lag_column(_rows_with_lag(), 124, 5)
    records = json.loads("".join(JsonFormatter().format(out)))
    assert records == [
        {"msg": "ok"},
        {"msg": "late", "lag_s": 237},
        {"msg": "early", "lag_s": -18000},
    ]


def test_toon_renders_unflagged_lag_as_dash() -> None:
    out = apply_lag_column(_rows_with_lag(), 124, 5)
    text = "".join(ToonFormatter().format(out))
    assert "result[3]{msg,lag_s}:" in text
    assert "  ok,-" in text
    assert "  late,237" in text


def test_ndjson_omits_lag_s_on_unflagged_rows() -> None:
    out = apply_lag_column(_rows_with_lag(), 124, 5)
    lines = [json.loads(line) for line in NdjsonFormatter().format(out)]
    assert lines == [
        {"msg": "ok"},
        {"msg": "late", "lag_s": 237},
        {"msg": "early", "lag_s": -18000},
    ]
