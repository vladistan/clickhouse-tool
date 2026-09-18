"""Tests for the connection adapter and logs-table resolution."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from clickhouse_tool.cli.wiring import (
    ConnectionParams,
    _unwrap_credential,
    open_client,
    resolve_logs_table,
)
from clickhouse_tool.core.client.factory import ClientProfile
from clickhouse_tool.core.config import ResolvedProfile, SsmRef
from clickhouse_tool.core.errors import ConfigError

pytestmark = pytest.mark.unit


def test_connection_params_satisfies_client_protocol_structurally() -> None:
    params = ConnectionParams(
        host="h",
        port=9000,
        transport="native",
        database="otel",
        user="u",
        password="p",  # noqa: S106 - test fixture value, never a real credential
        secure=False,
        connect_timeout=10.0,
        query_timeout=60.0,
    )
    assert isinstance(params, ClientProfile)
    assert isinstance(params.user, str)
    assert isinstance(params.connect_timeout, float)


def test_open_client_unwraps_literal_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    # Constructing a real backend here would import clickhouse_driver into
    # sys.modules for the rest of the test session, breaking the "the
    # contract layer imports no driver" isolation test elsewhere in the
    # suite. Capture the narrowed params instead of building a real client.
    import clickhouse_tool.cli.wiring as wiring_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(wiring_module, "make_client", lambda params: captured.setdefault("params", params))
    profile = ResolvedProfile(user="alice", password="secret", transport="native")  # noqa: S106
    open_client(profile)
    params = captured["params"]
    assert isinstance(params, ConnectionParams)
    assert params.user == "alice"
    assert params.password == "secret"  # pragma: allowlist secret


def test_unwrap_credential_raises_on_reference_that_survived_materialisation() -> None:
    with pytest.raises(ConfigError, match="unresolved secret reference"):
        _unwrap_credential(SsmRef(ssm="/x/y"), "user")


def test_open_client_defaults_absent_credentials_to_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.wiring as wiring_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(wiring_module, "make_client", lambda params: captured.setdefault("params", params))
    profile = ResolvedProfile(transport="native")
    open_client(profile)
    params = captured["params"]
    assert isinstance(params, ConnectionParams)
    assert params.user == ""
    assert params.password == ""


def test_unwrap_credential_reads_secretstr_value() -> None:
    assert _unwrap_credential(SecretStr("s3cret"), "password") == "s3cret"


def test_open_client_missing_driver_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.wiring as wiring_module

    def _boom(_params: object) -> object:
        raise ImportError("no module named clickhouse_driver")

    monkeypatch.setattr(wiring_module, "make_client", _boom)
    profile = ResolvedProfile(user="a", password="b", transport="native")  # noqa: S106
    with pytest.raises(ConfigError, match=r"clickhouse-driver.*clickhouse-tool\[native\]"):
        open_client(profile)


def test_resolve_logs_table_joins_database_and_logs_table() -> None:
    profile = ResolvedProfile(database="otel", logs_table="otel_logs")
    assert resolve_logs_table(profile) == "otel.otel_logs"


def test_resolve_logs_table_rejects_malformed_identifier() -> None:
    profile = ResolvedProfile(database="ot el", logs_table="otel_logs")
    with pytest.raises(ConfigError):
        resolve_logs_table(profile)
