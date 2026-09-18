"""Tests for NativeChClient."""

from __future__ import annotations

import sys

import pytest

from clickhouse_tool.core.errors import ConnectionFailed, SchemaError
from clickhouse_tool.core.models import SqlStatement

pytestmark = pytest.mark.unit


class FakeDriverClient:
    """Stand-in for ``clickhouse_driver.Client``."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.disconnected = False
        self.executed: list[str] = []
        self.executed_iter: list[str] = []

    def execute(self, sql, params=None, with_column_types=False):
        self.executed.append(sql)
        if sql == "RAISE_CODED":
            from clickhouse_driver.errors import ServerException

            raise ServerException("Code: 60. Table not found", code=60)
        if sql == "RAISE_UNCODED":
            from clickhouse_driver.errors import NetworkError

            raise NetworkError("connection refused")
        if with_column_types:
            return [(1, "a"), (2, "b")], [("id", "UInt32"), ("name", "String")]
        return [(1,), (2,)]

    def execute_iter(self, sql, params=None, with_column_types=False, **kwargs: object):
        self.executed_iter.append(sql)
        if sql == "MALFORMED_HEADER":

            def gen():
                yield "not-a-header"

            return gen()
        if sql == "RAISE_MID_STREAM":

            def gen():
                yield [("id", "UInt32")]
                from clickhouse_driver.errors import ServerException

                raise ServerException("Code: 159. Timeout", code=159)

            return gen()
        if sql == "EMPTY":

            def gen():
                return
                yield  # pragma: no cover

            return gen()

        def gen():
            yield [("id", "UInt32")]
            yield (1,)
            yield (2,)

        return gen()

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture
def fake_client(monkeypatch) -> FakeDriverClient:
    import clickhouse_driver

    holder: dict[str, FakeDriverClient] = {}

    def fake_ctor(**kwargs: object) -> FakeDriverClient:
        client = FakeDriverClient(**kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(clickhouse_driver, "Client", fake_ctor)
    from clickhouse_tool.core.client.native import NativeChClient

    NativeChClient(
        host="ch.example",
        port=9000,
        database="otel",
        user="ch_tool",
        password="secret",  # noqa: S106 - test fixture value, never a real credential
    )
    return holder["client"]


def _client(fake_client: FakeDriverClient):
    from clickhouse_tool.core.client.native import NativeChClient

    instance = NativeChClient.__new__(NativeChClient)
    instance._client = fake_client
    return instance


def test_native_client_not_imported_at_module_scope() -> None:
    sys.modules.pop("clickhouse_driver", None)
    import clickhouse_tool.core.client.native  # noqa: F401

    assert "clickhouse_driver" not in sys.modules


def test_execute_returns_rowset_with_column_metadata(fake_client) -> None:
    client = _client(fake_client)
    rowset = client.execute(SqlStatement(sql="SELECT id, name FROM t"))
    assert [c.name for c in rowset.columns] == ["id", "name"]
    assert rowset.rows == ((1, "a"), (2, "b"))
    assert rowset.row_count == 2


def test_execute_escapes_literal_percent_signs_but_not_placeholders(fake_client) -> None:
    client = _client(fake_client)
    client.execute(
        SqlStatement(
            sql="SELECT formatDateTime(Timestamp, '%Y-%m-%d') FROM t WHERE x = %(x)s",
            params={"x": "v"},
        )
    )
    assert fake_client.executed == [
        "SELECT formatDateTime(Timestamp, '%%Y-%%m-%%d') FROM t WHERE x = %(x)s"
    ]


def test_stream_escapes_literal_percent_signs(fake_client) -> None:
    client = _client(fake_client)
    list(client.stream(SqlStatement(sql="SELECT '%Y' FROM t")))
    assert fake_client.executed_iter == ["SELECT '%%Y' FROM t"]


def test_execute_translates_coded_server_error(fake_client) -> None:
    client = _client(fake_client)
    with pytest.raises(SchemaError):
        client.execute(SqlStatement(sql="RAISE_CODED"))


def test_execute_translates_uncoded_transport_error(fake_client) -> None:
    client = _client(fake_client)
    with pytest.raises(ConnectionFailed):
        client.execute(SqlStatement(sql="RAISE_UNCODED"))


def test_stream_never_surfaces_column_header_as_a_row(fake_client) -> None:
    client = _client(fake_client)
    rows = list(client.stream(SqlStatement(sql="SELECT id FROM t")))
    assert rows == [(1,), (2,)]


def test_stream_raises_schema_error_on_malformed_first_item(fake_client) -> None:
    client = _client(fake_client)
    with pytest.raises(SchemaError):
        list(client.stream(SqlStatement(sql="MALFORMED_HEADER")))


def test_stream_translates_mid_stream_failure(fake_client) -> None:
    from clickhouse_tool.core.errors import QueryTimeout

    client = _client(fake_client)
    with pytest.raises(QueryTimeout):
        list(client.stream(SqlStatement(sql="RAISE_MID_STREAM")))


def test_stream_empty_result_yields_nothing(fake_client) -> None:
    client = _client(fake_client)
    assert list(client.stream(SqlStatement(sql="EMPTY"))) == []


def test_stream_disconnects_on_early_abandonment(fake_client) -> None:
    client = _client(fake_client)
    gen = client.stream(SqlStatement(sql="SELECT id FROM t"))
    next(gen)
    gen.close()
    assert fake_client.disconnected is True


def test_close_disconnects(fake_client) -> None:
    client = _client(fake_client)
    client.close()
    assert fake_client.disconnected is True


def test_default_settings_carry_no_timeout(fake_client) -> None:
    assert fake_client.kwargs["settings"] == {"readonly": 2}


def test_configured_query_timeout_reaches_driver_settings(monkeypatch) -> None:
    import clickhouse_driver

    holder: dict[str, FakeDriverClient] = {}

    def fake_ctor(**kwargs: object) -> FakeDriverClient:
        client = FakeDriverClient(**kwargs)
        holder["client"] = client
        return client

    monkeypatch.setattr(clickhouse_driver, "Client", fake_ctor)
    from clickhouse_tool.core.client.native import NativeChClient

    NativeChClient(
        host="ch.example",
        port=9000,
        database="otel",
        user="ch_tool",
        password="secret",  # noqa: S106 - test fixture value, never a real credential
        query_timeout=45.0,
    )
    assert holder["client"].kwargs["settings"] == {"readonly": 2, "max_execution_time": 45.0}


def test_build_query_settings_omits_timeout_when_unset() -> None:
    from clickhouse_tool.core.client.native import build_query_settings

    assert build_query_settings(None) == {"readonly": 2}


def test_build_query_settings_carries_configured_timeout() -> None:
    from clickhouse_tool.core.client.native import build_query_settings

    assert build_query_settings(30.0) == {"readonly": 2, "max_execution_time": 30.0}
