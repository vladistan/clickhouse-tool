"""Tests for the client factory."""

from __future__ import annotations

import sys
from dataclasses import dataclass

import pytest

from clickhouse_tool.core.errors import ConfigError

pytestmark = pytest.mark.unit


@dataclass
class FakeProfile:
    host: str = "ch.example"
    port: int = 9000
    transport: str = "native"
    database: str = "otel"
    user: str = "ch_tool"
    password: str = "secret"  # noqa: S105 - test fixture value, never a real credential
    secure: bool = False
    connect_timeout: float = 10.0
    query_timeout: float = 60.0


def test_native_transport_selects_native_client(monkeypatch) -> None:
    import clickhouse_driver

    monkeypatch.setattr(clickhouse_driver, "Client", lambda **kwargs: object())
    from clickhouse_tool.core.client.factory import make_client
    from clickhouse_tool.core.client.native import NativeChClient

    client = make_client(FakeProfile(transport="native"))
    assert isinstance(client, NativeChClient)


def test_http_transport_selects_http_client(monkeypatch) -> None:
    import clickhouse_connect

    monkeypatch.setattr(clickhouse_connect, "get_client", lambda **kwargs: object())
    from clickhouse_tool.core.client.factory import make_client
    from clickhouse_tool.core.client.http import HttpChClient

    client = make_client(FakeProfile(transport="http"))
    assert isinstance(client, HttpChClient)


def test_unrecognised_transport_raises_before_any_socket_opens() -> None:
    from clickhouse_tool.core.client.factory import make_client

    for mod in ("clickhouse_driver", "clickhouse_connect"):
        sys.modules.pop(mod, None)

    with pytest.raises(ConfigError):
        make_client(FakeProfile(transport="grpc"))

    assert "clickhouse_driver" not in sys.modules
    assert "clickhouse_connect" not in sys.modules


def test_no_cross_backend_fallback(monkeypatch) -> None:
    """A failure constructing the selected backend must not try the other one."""
    import clickhouse_driver

    def failing_ctor(**kwargs: object):
        raise RuntimeError("native construction failed")

    monkeypatch.setattr(clickhouse_driver, "Client", failing_ctor)

    http_attempted = False

    def fake_get_client(**kwargs: object):
        nonlocal http_attempted
        http_attempted = True
        return object()

    import clickhouse_connect

    monkeypatch.setattr(clickhouse_connect, "get_client", fake_get_client)

    from clickhouse_tool.core.client.factory import make_client

    with pytest.raises(RuntimeError):
        make_client(FakeProfile(transport="native"))

    assert http_attempted is False


def test_both_transports_receive_the_same_configured_query_timeout(monkeypatch) -> None:
    import clickhouse_connect
    import clickhouse_driver

    captured: dict[str, object] = {}

    def fake_native_ctor(**kwargs: object):
        captured["native_settings"] = kwargs["settings"]
        return object()

    def fake_http_ctor(**kwargs: object):
        captured["http_settings"] = kwargs["settings"]
        return object()

    monkeypatch.setattr(clickhouse_driver, "Client", fake_native_ctor)
    monkeypatch.setattr(clickhouse_connect, "get_client", fake_http_ctor)

    from clickhouse_tool.core.client.factory import make_client

    profile = FakeProfile(query_timeout=45.0)
    make_client(FakeProfile(transport="native", query_timeout=profile.query_timeout))
    make_client(FakeProfile(transport="http", query_timeout=profile.query_timeout))

    assert captured["native_settings"]["max_execution_time"] == 45.0
    assert captured["http_settings"]["max_execution_time"] == 45.0
