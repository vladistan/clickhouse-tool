"""Tests for the logs verb: CLI flag mapping and count conversion."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli.main import app
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.core.models import RowSet, SqlStatement
from clickhouse_tool.query.builder import build_count, build_logs
from clickhouse_tool.query.intents import CountIntent, Filters, LogsIntent

pytestmark = pytest.mark.unit

runner = CliRunner()
_TABLE = "otel.otel_logs"


@pytest.fixture(autouse=True)
def _no_real_connection(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Stub the CLI's connection and rendering, capturing the built statement."""
    import clickhouse_tool.cli.commands.facets as facets_module
    import clickhouse_tool.cli.commands.logs as logs_module

    captured: dict[str, object] = {}

    def _fake_load_profile(_profile: str | None, **_kwargs: object) -> ResolvedProfile:
        return ResolvedProfile()

    def _fake_open_client(_profile: ResolvedProfile) -> object:
        return object()

    def _fake_run_statement(_client: object, statement: SqlStatement, _formatter: object, **kwargs: object) -> None:
        captured["statement"] = statement
        captured["table"] = kwargs.get("table")

    for module in (logs_module, facets_module):
        monkeypatch.setattr(module.wiring, "load_profile", _fake_load_profile)
        monkeypatch.setattr(module.wiring, "open_client", _fake_open_client)
    monkeypatch.setattr(logs_module, "run_statement", _fake_run_statement)
    monkeypatch.setattr(logs_module.wiring, "resolve_logs_table", lambda _p: _TABLE)
    return captured


def test_every_logs_flag_reaches_its_intent(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(
        app,
        [
            "logs",
            "--host",
            "fw7",
            "--service",
            "api",
            "--namespace",
            "prod",
            "--container",
            "nginx",
            "--level",
            "warn",
            "-t",
            "15m",
            "--search",
            "refused",
        ],
    )
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    for value in ("fw7", "api", "prod", "nginx", "refused"):
        assert value in statement.params.values()


def test_full_and_raw_request_every_column_and_set_nested_output() -> None:
    for kwargs in ({"full": True}, {"raw": True}):
        statement = build_logs(LogsIntent(**kwargs), _TABLE)
        assert "SELECT *" in statement.sql
        assert statement.meta["nested_output"] is True


def test_unknown_level_is_rejected_listing_accepted_set(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["logs", "--level", "critical"])
    assert result.exit_code != 0


def test_unknown_sort_is_rejected_listing_accepted_set(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["logs", "--sort", "bogus"])
    assert result.exit_code != 0


def test_count_flag_produces_a_single_row_result_shape(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["logs", "--count", "--host", "fw7"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "count()" in statement.sql
    assert "ORDER BY" not in statement.sql


def test_count_conversion_carries_filters_across_unchanged() -> None:
    logs_intent = LogsIntent(filters=Filters(host="fw7", service="api"))
    count_intent = CountIntent.from_logs_intent(logs_intent)
    logs_statement = build_logs(logs_intent, _TABLE)
    count_statement = build_count(count_intent, _TABLE)
    assert logs_statement.params["host"] == count_statement.params["host"]
    assert logs_statement.params["service"] == count_statement.params["service"]


def test_time_range_defaults_to_the_profile_window_when_flag_unset(
    monkeypatch: pytest.MonkeyPatch, _no_real_connection: dict[str, object]
) -> None:
    import clickhouse_tool.cli.commands.logs as logs_module

    monkeypatch.setattr(
        logs_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile(default_window="7h")
    )
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert 7 in statement.params.values()


def test_explicit_time_range_flag_wins_over_the_profile_default(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["logs", "-t", "3h"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert 3 in statement.params.values()


def test_follow_and_count_together_is_rejected(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["logs", "--follow", "--count"])
    assert result.exit_code != 0


def test_follow_and_sort_together_is_rejected(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["logs", "--follow", "--sort", "ts:desc"])
    assert result.exit_code != 0


def test_follow_seeds_from_the_latest_matching_row_when_one_exists(
    monkeypatch: pytest.MonkeyPatch, _no_real_connection: dict[str, object]
) -> None:
    import clickhouse_tool.cli.commands.logs as logs_module

    calls: list[SqlStatement] = []

    class _FakeClient:
        def execute(self, statement: SqlStatement) -> RowSet:
            calls.append(statement)
            return RowSet(columns=(), rows=(("2026-01-01 00:00:00.123456789",),), row_count=1)

        def close(self) -> None:
            pass

    monkeypatch.setattr(logs_module.wiring, "open_client", lambda _p: _FakeClient())

    seeds: dict[str, object] = {}

    def _fake_run_follow(_client: object, *, since: str, **_kwargs: object) -> None:
        seeds["since"] = since

    monkeypatch.setattr(logs_module, "run_follow", _fake_run_follow)

    result = runner.invoke(app, ["logs", "--follow"])

    assert result.exit_code == 0, result.stdout
    assert seeds["since"] == "2026-01-01 00:00:00.123456789"
    assert len(calls) == 1
    assert "ORDER BY Timestamp DESC LIMIT 1" in calls[0].sql


def test_follow_falls_back_to_the_window_cursor_when_nothing_matches(
    monkeypatch: pytest.MonkeyPatch, _no_real_connection: dict[str, object]
) -> None:
    import clickhouse_tool.cli.commands.logs as logs_module

    class _FakeClient:
        def execute(self, statement: SqlStatement) -> RowSet:
            if "ORDER BY Timestamp DESC LIMIT 1" in statement.sql:
                return RowSet(columns=(), rows=(), row_count=0)
            return RowSet(columns=(), rows=(("2026-01-01 00:00:00",),), row_count=1)

        def close(self) -> None:
            pass

    monkeypatch.setattr(logs_module.wiring, "open_client", lambda _p: _FakeClient())

    seeds: dict[str, object] = {}

    def _fake_run_follow(_client: object, *, since: str, **_kwargs: object) -> None:
        seeds["since"] = since

    monkeypatch.setattr(logs_module, "run_follow", _fake_run_follow)

    result = runner.invoke(app, ["logs", "--follow"])

    assert result.exit_code == 0, result.stdout
    assert seeds["since"] == "2026-01-01 00:00:00"


def test_utc_flag_binds_utc_as_the_timezone_param(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["logs", "--utc"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert statement.params["tz"] == "UTC"


def test_without_utc_flag_resolves_the_profiles_configured_timezone(
    monkeypatch: pytest.MonkeyPatch, _no_real_connection: dict[str, object]
) -> None:
    import clickhouse_tool.cli.commands.logs as logs_module

    monkeypatch.setattr(
        logs_module.wiring,
        "load_profile",
        lambda _p, **_k: ResolvedProfile(default_timezone="Asia/Tokyo"),
    )
    result = runner.invoke(app, ["logs"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert statement.params["tz"] == "Asia/Tokyo"
