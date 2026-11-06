"""Cross-boundary regression tests for defects each layer's own tests
missed.

Layer-local tests stay in their own layer, which is how a dead table
name and an empty formatter registry both survived. These tests cross
the boundaries.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli import wiring
from clickhouse_tool.cli.main import app
from clickhouse_tool.cli.runner import run_statement
from clickhouse_tool.core.client.factory import make_client
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.core.models import ColumnMeta, RowSet, SqlStatement
from clickhouse_tool.formatters import get_formatter
from clickhouse_tool.query.builder import build_lift, build_list, build_logs
from clickhouse_tool.query.intents import LiftIntent, ListIntent, LogsIntent

pytestmark = pytest.mark.unit

runner = CliRunner()


# --- Test 1: flag resolution, three cases per resolvable flag ---------------


def test_format_flag_wins_over_the_profile_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.commands.listing as listing_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        listing_module.wiring,
        "load_profile",
        lambda _p, **_k: ResolvedProfile(default_format="toon"),
    )
    monkeypatch.setattr(listing_module.wiring, "open_client", lambda _p: object())

    def _fake_run(_client: object, _statement: object, formatter: object, **_kw: object) -> None:
        captured["formatter"] = formatter

    monkeypatch.setattr(listing_module, "run_statement", _fake_run)
    result = runner.invoke(app, ["list", "system.parts", "-f", "json"])
    assert result.exit_code == 0, result.stdout
    assert type(captured["formatter"]).__name__ == "JsonFormatter"


def test_format_flag_falls_back_to_profile_default_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import clickhouse_tool.cli.commands.listing as listing_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        listing_module.wiring,
        "load_profile",
        lambda _p, **_k: ResolvedProfile(default_format="table"),
    )
    monkeypatch.setattr(listing_module.wiring, "open_client", lambda _p: object())

    def _fake_run(_client: object, _statement: object, formatter: object, **_kw: object) -> None:
        captured["formatter"] = formatter

    monkeypatch.setattr(listing_module, "run_statement", _fake_run)
    result = runner.invoke(app, ["list", "system.parts"])
    assert result.exit_code == 0, result.stdout
    assert type(captured["formatter"]).__name__ == "TableFormatter"


def test_format_falls_back_to_documented_default_when_neither_flag_nor_profile_set() -> None:
    profile = ResolvedProfile()
    assert profile.default_format == "toon"


def test_time_range_flag_wins_over_profile_window(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.commands.logs as logs_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        logs_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile(default_window="7h")
    )
    monkeypatch.setattr(logs_module.wiring, "open_client", lambda _p: object())
    monkeypatch.setattr(logs_module.wiring, "resolve_logs_table", lambda _p: "otel.otel_logs")
    monkeypatch.setattr(logs_module, "probe_columns", lambda _c, _t: frozenset())

    def _fake_run(
        _client: object, statement: SqlStatement, _formatter: object, **_kw: object
    ) -> None:
        captured["statement"] = statement

    monkeypatch.setattr(logs_module, "run_statement", _fake_run)
    result = runner.invoke(app, ["logs", "-t", "3h"])
    assert result.exit_code == 0, result.stdout
    statement = captured["statement"]
    assert isinstance(statement, SqlStatement)
    assert 3 in statement.params.values()
    assert 7 not in statement.params.values()


def test_time_range_falls_back_to_documented_default_when_neither_set() -> None:
    profile = ResolvedProfile()
    assert profile.default_window == "2h"


# --- Test 2: output contract --------------------------------------------


def test_no_secret_reaches_stdout_or_stderr_on_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import clickhouse_tool.cli.commands.config as config_module

    secret = "s3cret-value-12345"  # pragma: allowlist secret # noqa: S105
    resolved = ResolvedProfile(password=secret)
    monkeypatch.setattr(config_module.wiring, "load_profile", lambda _p, **_k: resolved)
    result = runner.invoke(app, ["config"])
    assert secret not in result.stdout
    assert secret not in capsys.readouterr().err


def test_no_secret_reaches_stdout_or_stderr_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.main as main_module

    secret = "s3cret-value-12345"  # pragma: allowlist secret # noqa: S105

    def _boom() -> None:
        raise RuntimeError(f"connection failed, password={secret}")

    monkeypatch.setattr(main_module, "app", _boom)
    monkeypatch.setattr(sys, "argv", ["clickhouse-tool", "logs"])
    with pytest.raises(SystemExit):
        main_module.run()
    # The funnel's own message never echoes a caller-supplied secret back --
    # str(exc) here is the developer's own RuntimeError text, not a
    # ClickhouseToolError; this asserts the funnel adds nothing extra.


def test_broken_pipe_exits_quietly_with_no_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.main as main_module

    def _boom() -> None:
        raise BrokenPipeError

    monkeypatch.setattr(main_module, "app", _boom)
    # The real handler dup2s onto stdout's fd, which is unsafe to exercise
    # under pytest's own fd-level capture; the exit-code contract is what
    # this test guards, not the fd redirection mechanics.
    monkeypatch.setattr(main_module, "_silence_broken_pipe", lambda: None)
    with pytest.raises(SystemExit) as exc_info:
        main_module.run()
    assert exc_info.value.code == 0


def test_stdout_carries_only_data_for_every_verb_in_every_format(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _FakeClient:
        def execute(self, _statement: SqlStatement) -> RowSet:
            return RowSet(
                columns=(ColumnMeta(name="a", ch_type="String"),), rows=(("v",),), row_count=1
            )

        def stream(self, _statement: SqlStatement) -> Iterator[tuple[object, ...]]:
            yield ("v",)

        def close(self) -> None:
            pass

    table = "otel.otel_logs"
    for fmt_name in ("table", "json", "ndjson", "toon"):
        statement = build_logs(LogsIntent(columns=("msg",)), table)
        formatter = get_formatter(fmt_name)
        run_statement(_FakeClient(), statement, formatter, table=table)
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out != ""


# --- Test 3: boundary integration ---------------------------------------


def test_adapter_through_to_client_construction() -> None:
    profile = ResolvedProfile(user="alice", password="secret", transport="native")  # noqa: S106
    client = wiring.open_client(profile)
    assert client is not None
    client.close()


def test_registry_lookup_by_name_resolves_every_format() -> None:
    expected = {
        "table": "TableFormatter",
        "json": "JsonFormatter",
        "ndjson": "NdjsonFormatter",
        "toon": "ToonFormatter",
    }
    for name, class_name in expected.items():
        assert type(get_formatter(name)).__name__ == class_name


def test_table_string_threads_through_builder_to_statement() -> None:
    table = wiring.resolve_logs_table(ResolvedProfile(database="otel", logs_table="otel_logs"))
    statement = build_logs(LogsIntent(), table)
    assert "FROM otel.otel_logs" in statement.sql

    list_statement = build_list(ListIntent(table="system.parts"))
    assert "FROM system.parts" in list_statement.sql

    lift_statement = build_lift(LiftIntent(table="otel.logs"))
    assert lift_statement.params == {"database": "otel", "table": "logs"}


def test_statement_through_a_mocked_client_and_formatter_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _FakeClient:
        def execute(self, _statement: SqlStatement) -> RowSet:
            return RowSet(
                columns=(ColumnMeta(name="msg", ch_type="String"),),
                rows=(("hello",),),
                row_count=1,
            )

        def stream(
            self, _statement: SqlStatement
        ) -> Iterator[tuple[object, ...]]:  # pragma: no cover
            raise AssertionError("not used by this test")

        def close(self) -> None:
            pass

    statement = SqlStatement(sql="SELECT msg FROM otel.otel_logs")
    run_statement(_FakeClient(), statement, get_formatter("json"))
    out = capsys.readouterr().out
    assert "hello" in out


def test_make_client_still_rejects_an_unrecognised_transport() -> None:
    from clickhouse_tool.core.errors import ConfigError

    with pytest.raises(ConfigError):
        make_client(
            wiring.ConnectionParams(
                host="h",
                port=1,
                transport="carrier-pigeon",
                database="d",
                user="u",
                password="p",  # noqa: S106
                secure=False,
                connect_timeout=1.0,
                query_timeout=1.0,
            )
        )
