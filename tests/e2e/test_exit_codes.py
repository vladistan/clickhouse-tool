"""One end-to-end case per ExitCode member, driven through ``main.run()``.

``run()`` is the sole place an exception becomes a process exit status.
Every case asserts on that status, never on a raised exception.
"""

from __future__ import annotations

import sys

import pytest
from pydantic import SecretStr

from clickhouse_tool.cli.main import app
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.core.errors import (
    AuthFailed,
    ConfigError,
    ConnectionFailed,
    PermissionDenied,
    QueryTimeout,
    ResultTooLarge,
    SchemaError,
    ServerError,
    ServerResourceError,
    UnsupportedFilterError,
)
from clickhouse_tool.core.exit_codes import ExitCode

pytestmark = pytest.mark.unit


class _RaisingClient:
    """A ChClient stand-in whose ``execute`` raises a chosen typed error."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def execute(self, _statement: object) -> object:
        raise self._error

    def stream(self, _statement: object) -> object:
        raise self._error

    def close(self) -> None:
        pass


def _run_logs_with_client_error(monkeypatch: pytest.MonkeyPatch, error: Exception) -> int:
    import clickhouse_tool.cli.commands.logs as logs_module
    import clickhouse_tool.cli.main as main_module

    monkeypatch.setattr(logs_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile())
    monkeypatch.setattr(
        logs_module.wiring, "resolve_logs_table", lambda _resolved: "otel.otel_logs"
    )
    monkeypatch.setattr(logs_module.wiring, "open_client", lambda _resolved: _RaisingClient(error))
    monkeypatch.setattr(sys, "argv", ["clickhouse-tool", "logs"])
    with pytest.raises(SystemExit) as exc_info:
        main_module.run()
    return exc_info.value.code


def test_success_exits_zero() -> None:
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == ExitCode.SUCCESS == 0


def test_general_error_exits_one(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.main as main_module

    monkeypatch.setattr(main_module, "app", lambda: (_ for _ in ()).throw(ValueError("boom")))
    monkeypatch.setattr(sys, "argv", ["clickhouse-tool", "logs"])
    with pytest.raises(SystemExit) as exc_info:
        main_module.run()
    assert exc_info.value.code == ExitCode.GENERAL_ERROR == 1


def test_usage_error_exits_two() -> None:
    from typer.testing import CliRunner

    result = CliRunner().invoke(app, ["cluster-health"])
    assert result.exit_code == ExitCode.USAGE_ERROR == 2


def test_config_error_exits_three(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, ConfigError("bad config"))
    assert code == ExitCode.CONFIG_ERROR == 3


def test_connection_failed_exits_four(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, ConnectionFailed("unreachable"))
    assert code == ExitCode.CONNECTION_FAILED == 4


def test_auth_failed_exits_five(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, AuthFailed("bad credentials", code=193))
    assert code == ExitCode.AUTH_FAILED == 5


def test_query_timeout_exits_six(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, QueryTimeout("timed out", code=159))
    assert code == ExitCode.QUERY_TIMEOUT == 6


def test_result_too_large_exits_seven(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, ResultTooLarge("too many rows", code=396))
    assert code == ExitCode.RESULT_TOO_LARGE == 7


def test_server_resource_error_exits_eight(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, ServerResourceError("out of memory", code=241))
    assert code == ExitCode.SERVER_RESOURCE_ERROR == 8


def test_permission_denied_exits_nine(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, PermissionDenied("not authorized", code=164))
    assert code == ExitCode.PERMISSION_DENIED == 9


def test_schema_error_exits_ten(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, SchemaError("unknown column", code=47))
    assert code == ExitCode.SCHEMA_ERROR == 10


def test_unsupported_filter_exits_eleven(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, UnsupportedFilterError("no exporter column"))
    assert code == ExitCode.UNSUPPORTED_FILTER == 11


def test_server_error_exits_twelve(monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run_logs_with_client_error(monkeypatch, ServerError("unmapped failure", code=999))
    assert code == ExitCode.SERVER_ERROR == 12


def test_no_case_leaks_a_secret(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """A resolved credential must never reach stdout/stderr on any failure path.

    ``password`` is the field a failure path could leak by accident;
    every typed error's ``.message`` carries only server-provided text.
    """
    secret = "sk-super-secret-value"  # noqa: S105 - fixture value, never a real credential
    import clickhouse_tool.cli.commands.logs as logs_module
    import clickhouse_tool.cli.main as main_module

    profile = ResolvedProfile(password=SecretStr(secret))
    monkeypatch.setattr(logs_module.wiring, "load_profile", lambda _p, **_k: profile)
    monkeypatch.setattr(
        logs_module.wiring, "resolve_logs_table", lambda _resolved: "otel.otel_logs"
    )
    monkeypatch.setattr(
        logs_module.wiring,
        "open_client",
        lambda _resolved: _RaisingClient(ConnectionFailed(f"connect failed to {_resolved.host}")),
    )
    monkeypatch.setattr(sys, "argv", ["clickhouse-tool", "logs"])
    with pytest.raises(SystemExit):
        main_module.run()
    captured = capsys.readouterr()
    assert secret not in captured.out
    assert secret not in captured.err


def test_usage_versus_config_distinction_holds() -> None:
    """Parse failures give exit 2; invalid flag combinations give exit 3."""
    from typer.testing import CliRunner

    parse_failure = CliRunner().invoke(app, ["not-a-real-command"])
    assert parse_failure.exit_code == 2

    import clickhouse_tool.cli.main as main_module

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            sys, "argv", ["clickhouse-tool", "hosts", "--stream", "metrics", "--level", "error"]
        )
        with pytest.raises(SystemExit) as exc_info:
            main_module.run()
        assert exc_info.value.code == 3
