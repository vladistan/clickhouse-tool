"""Fixtures for the live integration harness (``-m integration``).

Connection details come from the environment, never the config layer.
Fixtures skip cleanly when unreachable. Opt-in (``pytest -m
integration``), not part of the offline gate.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import pytest


@dataclass(frozen=True)
class PilotConnection:
    host: str
    native_port: int
    http_port: int
    database: str
    user: str
    password: str
    secure: bool = False


def _pilot_connection() -> PilotConnection | None:
    host = os.environ.get("CLICKHOUSE_TOOL_TEST_HOST")
    user = os.environ.get("CLICKHOUSE_TOOL_TEST_USER")
    password = os.environ.get("CLICKHOUSE_TOOL_TEST_PASSWORD")
    if not host or not user or password is None:
        return None
    return PilotConnection(
        host=host,
        native_port=int(os.environ.get("CLICKHOUSE_TOOL_TEST_NATIVE_PORT", "9000")),
        http_port=int(os.environ.get("CLICKHOUSE_TOOL_TEST_HTTP_PORT", "8123")),
        database=os.environ.get("CLICKHOUSE_TOOL_TEST_DATABASE", "otel"),
        user=user,
        password=password,
    )


@pytest.fixture
def pilot() -> PilotConnection:
    connection = _pilot_connection()
    if connection is None:
        pytest.skip(
            "pilot connection not configured -- set CLICKHOUSE_TOOL_TEST_HOST/"
            "USER/PASSWORD to run the live integration suite"
        )
    return connection


@pytest.fixture
def native_client(pilot: PilotConnection):
    from clickhouse_tool.core.client.native import NativeChClient
    from clickhouse_tool.core.errors import ClickhouseToolError

    client = NativeChClient(
        host=pilot.host,
        port=pilot.native_port,
        database=pilot.database,
        user=pilot.user,
        password=pilot.password,
        secure=pilot.secure,
    )
    try:
        client.ping()
    except ClickhouseToolError as exc:
        pytest.skip(f"pilot unreachable over native transport: {exc}")
    yield client
    client.close()


@pytest.fixture
def http_client(pilot: PilotConnection):
    from clickhouse_tool.core.client.http import HttpChClient
    from clickhouse_tool.core.errors import ClickhouseToolError

    client = HttpChClient(
        host=pilot.host,
        port=pilot.http_port,
        database=pilot.database,
        user=pilot.user,
        password=pilot.password,
        secure=pilot.secure,
    )
    try:
        client.ping()
    except ClickhouseToolError as exc:
        pytest.skip(f"pilot unreachable over HTTP transport: {exc}")
    yield client
    client.close()
