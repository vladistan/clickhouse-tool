"""Live integration harness: both backends against the real pilot.

Run with: ``uv run pytest -m integration``

Assertions check shape and invariants only -- never exact row counts or
message content, since the pilot is live data with a TTL change coming.
"""

from __future__ import annotations

import pytest

from clickhouse_tool.core.models import SqlStatement

pytestmark = pytest.mark.integration


def test_native_ping_execute_stream_close(native_client) -> None:
    native_client.ping()

    rowset = native_client.execute(SqlStatement(sql="SELECT 1 AS one"))
    assert rowset.row_count >= 1
    assert rowset.columns[0].name == "one"

    rows = list(native_client.stream(SqlStatement(sql="SELECT number FROM system.numbers LIMIT 5")))
    assert len(rows) == 5


def test_http_ping_execute_stream_close(http_client) -> None:
    http_client.ping()

    rowset = http_client.execute(SqlStatement(sql="SELECT 1 AS one"))
    assert rowset.row_count >= 1
    assert rowset.columns[0].name == "one"

    rows = list(http_client.stream(SqlStatement(sql="SELECT number FROM system.numbers LIMIT 5")))
    assert len(rows) == 5


def test_first_row_observable_before_native_stream_completes(native_client) -> None:
    stream = native_client.stream(
        SqlStatement(sql="SELECT number FROM system.numbers LIMIT 1000000")
    )
    first = next(stream)
    assert isinstance(first, tuple)
    stream.close()


def test_first_row_observable_before_http_stream_completes(http_client) -> None:
    stream = http_client.stream(
        SqlStatement(sql="SELECT number FROM system.numbers LIMIT 1000000")
    )
    first = next(stream)
    assert isinstance(first, tuple)
    stream.close()
