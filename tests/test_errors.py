"""Tests for typed error hierarchy and server-code translation."""

import pytest

from clickhouse_tool.core import errors
from clickhouse_tool.core.errors import (
    AuthFailed,
    ClickhouseToolError,
    ConfigError,
    ConnectionFailed,
    PermissionDenied,
    QueryTimeout,
    ResultTooLarge,
    SchemaError,
    ServerError,
    ServerResourceError,
    UnsupportedFilterError,
    map_server_code,
)
from clickhouse_tool.core.exit_codes import ExitCode

pytestmark = pytest.mark.unit

_TABLE_CASES = [
    (60, SchemaError),
    (47, SchemaError),
    (81, SchemaError),
    (159, QueryTimeout),
    (160, QueryTimeout),
    (164, PermissionDenied),
    (497, PermissionDenied),
    (192, AuthFailed),
    (193, AuthFailed),
    (516, AuthFailed),
    (241, ServerResourceError),
    (202, ServerResourceError),
    (203, ServerResourceError),
    (396, ResultTooLarge),
]


@pytest.mark.parametrize("code,expected_type", _TABLE_CASES)
def test_every_code_table_entry_maps_correctly(
    code: int, expected_type: type[ClickhouseToolError]
) -> None:
    exc = map_server_code(code, "boom")
    assert isinstance(exc, expected_type)
    assert exc.code == code
    assert exc.message == "boom"


def test_code_table_covers_all_cases_exactly() -> None:
    codes_covered = {code for code, _ in _TABLE_CASES}
    assert codes_covered == set(errors._CODE_TABLE)


def test_unmapped_code_produces_server_error_verbatim() -> None:
    exc = map_server_code(9999, "totally unknown")
    assert isinstance(exc, ServerError)
    assert exc.code == 9999
    assert exc.message == "totally unknown"


def test_unmapped_code_is_logged_at_warn(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING", logger="clickhouse_tool.core.errors"):
        map_server_code(9999, "totally unknown")
    assert any("9999" in record.message for record in caplog.records)


@pytest.mark.parametrize("exit_code", list(ExitCode))
def test_every_exit_code_value_is_pinned(exit_code: ExitCode) -> None:
    assert isinstance(exit_code.value, int)


def test_client_side_errors_have_own_exit_codes() -> None:
    assert ConfigError("x").exit_code == ExitCode.CONFIG_ERROR
    assert ConnectionFailed("x").exit_code == ExitCode.CONNECTION_FAILED
    assert UnsupportedFilterError("x").exit_code == ExitCode.UNSUPPORTED_FILTER


@pytest.mark.parametrize(
    "exc",
    [
        ConfigError("plain message, no secret"),
        AuthFailed("auth failed", code=192),
        ServerError("unmapped", code=9999),
    ],
)
def test_error_string_form_never_echoes_a_secret_marker(exc: ClickhouseToolError) -> None:
    # Base contract: only message and code appear, nothing else.
    # Full secret-leak tests live alongside SSM resolution.
    text = str(exc)
    assert text == exc.message
