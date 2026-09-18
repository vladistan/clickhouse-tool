"""Tests for HttpChClient."""

from __future__ import annotations

import sys

import pytest

from clickhouse_tool.core.errors import ConnectionFailed, PermissionDenied
from clickhouse_tool.core.models import SqlStatement

pytestmark = pytest.mark.unit


class FakeQueryResult:
    def __init__(self, column_names, column_types, rows) -> None:
        self.column_names = column_names
        self.column_types = column_types
        self.result_rows = rows


class FakeStreamContext:
    """Stand-in for clickhouse_connect's StreamContext."""

    def __init__(self, rows, raises=None) -> None:
        self._rows = rows
        self._raises = raises
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.closed = True

    def __iter__(self):
        yield from self._rows
        if self._raises is not None:
            raise self._raises


class FakeConnectClient:
    """Stand-in for ``clickhouse_connect``'s HTTP client."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.closed = False

    def ping(self) -> bool:
        return True

    def query(self, sql, parameters=None):
        if sql == "RAISE_CODED":
            from clickhouse_connect.driver.exceptions import DatabaseError

            raise DatabaseError("(FORBIDDEN) Code: 497. Not enough privileges", code=497)
        if sql == "RAISE_UNCODED":
            from clickhouse_connect.driver.exceptions import OperationalError

            raise OperationalError("connection refused")
        return FakeQueryResult(["id", "name"], ["UInt32", "String"], [(1, "a"), (2, "b")])

    def query_rows_stream(self, sql, parameters=None):
        if sql == "RAISE_ON_OPEN":
            from clickhouse_connect.driver.exceptions import OperationalError

            raise OperationalError("connection refused")
        if sql == "RAISE_MID_STREAM":
            from clickhouse_connect.driver.exceptions import DatabaseError

            return FakeStreamContext([(1,)], raises=DatabaseError("Code: 497. denied", code=497))
        return FakeStreamContext([(1,), (2,)])

    def close(self) -> None:
        self.closed = True


def _client(fake: FakeConnectClient):
    from clickhouse_tool.core.client.http import HttpChClient

    instance = HttpChClient.__new__(HttpChClient)
    instance._client = fake
    return instance


def test_http_client_not_imported_at_module_scope() -> None:
    sys.modules.pop("clickhouse_connect", None)
    import clickhouse_tool.core.client.http  # noqa: F401

    assert "clickhouse_connect" not in sys.modules


def test_execute_returns_rowset_shaped_like_native() -> None:
    client = _client(FakeConnectClient())
    rowset = client.execute(SqlStatement(sql="SELECT id, name FROM t"))
    assert [c.name for c in rowset.columns] == ["id", "name"]
    assert rowset.rows == ((1, "a"), (2, "b"))
    assert rowset.row_count == 2


def test_execute_translates_coded_server_error() -> None:
    client = _client(FakeConnectClient())
    with pytest.raises(PermissionDenied):
        client.execute(SqlStatement(sql="RAISE_CODED"))


def test_execute_translates_uncoded_transport_error() -> None:
    client = _client(FakeConnectClient())
    with pytest.raises(ConnectionFailed):
        client.execute(SqlStatement(sql="RAISE_UNCODED"))


def test_stream_uses_row_stream_not_buffering_query(monkeypatch) -> None:
    fake = FakeConnectClient()
    calls: list[str] = []
    original = fake.query

    def tracking_query(*args: object, **kwargs: object):
        calls.append("query")
        return original(*args, **kwargs)

    monkeypatch.setattr(fake, "query", tracking_query)
    client = _client(fake)
    rows = list(client.stream(SqlStatement(sql="SELECT id FROM t")))
    assert rows == [(1,), (2,)]
    assert calls == []


def test_stream_translates_failure_opening(monkeypatch) -> None:
    client = _client(FakeConnectClient())
    with pytest.raises(ConnectionFailed):
        list(client.stream(SqlStatement(sql="RAISE_ON_OPEN")))


def test_stream_translates_mid_stream_failure() -> None:
    client = _client(FakeConnectClient())
    with pytest.raises(PermissionDenied):
        list(client.stream(SqlStatement(sql="RAISE_MID_STREAM")))


def test_stream_closes_context_on_early_abandonment() -> None:
    fake = FakeConnectClient()
    ctx = fake.query_rows_stream("SELECT id FROM t")
    fake.query_rows_stream = lambda *a, **k: ctx
    client = _client(fake)
    gen = client.stream(SqlStatement(sql="SELECT id FROM t"))
    next(gen)
    gen.close()
    assert ctx.closed is True


def test_close_closes_underlying_client() -> None:
    fake = FakeConnectClient()
    client = _client(fake)
    client.close()
    assert fake.closed is True
