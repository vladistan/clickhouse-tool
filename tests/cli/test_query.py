"""Tests for the raw-SQL query verb: input resolution and parameter parsing."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli.commands.query import _parse_params, _resolve_sql
from clickhouse_tool.cli.main import app
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.models import SqlStatement

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_positional_argument_is_used_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert _resolve_sql("SELECT 1") == "SELECT 1"


def test_piped_input_is_used_when_no_argument_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT 2"))
    assert _resolve_sql(None) == "SELECT 2"


def test_both_supplied_fails_before_any_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT 2"))
    with pytest.raises(ConfigError):
        _resolve_sql("SELECT 1")


def test_neither_with_a_terminal_attached_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    with pytest.raises(ConfigError):
        _resolve_sql(None)


def test_repeated_param_flags_collect_into_named_values_split_on_first_separator() -> None:
    params = _parse_params(["a=1", "b=x=y"])
    assert params == {"a": "1", "b": "x=y"}


def test_malformed_param_without_separator_raises() -> None:
    with pytest.raises(ConfigError):
        _parse_params(["missing-separator"])


def test_query_verb_wraps_sql_and_params_with_no_table_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import clickhouse_tool.cli.commands.query as query_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(query_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile())
    monkeypatch.setattr(query_module.wiring, "open_client", lambda _p: object())

    def _fake_run_statement(_client: object, statement: SqlStatement, _formatter: object, **kwargs: object) -> None:
        captured["statement"] = statement
        captured["table"] = kwargs.get("table")

    monkeypatch.setattr(query_module, "run_statement", _fake_run_statement)
    # sql-resolution's stdin-vs-argument edge cases are covered directly
    # above; CliRunner's stdin is never a tty, which would otherwise trip
    # the "both supplied" branch for every CliRunner invocation.
    monkeypatch.setattr(query_module, "_resolve_sql", lambda sql: sql)

    result = runner.invoke(app, ["query", "SELECT 1", "--param", "x=5"])
    assert result.exit_code == 0, result.stdout
    statement = captured["statement"]
    assert isinstance(statement, SqlStatement)
    assert statement.sql == "SELECT 1"
    assert statement.params == {"x": "5"}
    assert captured["table"] is None
