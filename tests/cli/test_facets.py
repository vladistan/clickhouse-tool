"""Tests for the hosts/services facet verbs: construction and stream selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli.commands.facets import _humanize_last_seen
from clickhouse_tool.cli.main import app
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.core.models import ColumnMeta, RowSet, SqlStatement

pytestmark = pytest.mark.unit

runner = CliRunner()
_TABLE = "otel.otel_logs"
_METRICS_TABLE = "otel.otel_metrics_gauge"


@pytest.fixture(autouse=True)
def _no_real_connection(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    import clickhouse_tool.cli.commands.facets as facets_module

    captured: dict[str, object] = {}

    monkeypatch.setattr(
        facets_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile()
    )
    monkeypatch.setattr(facets_module.wiring, "open_client", lambda _p: object())
    monkeypatch.setattr(facets_module.wiring, "resolve_logs_table", lambda _p: _TABLE)
    monkeypatch.setattr(facets_module.wiring, "resolve_metrics_table", lambda _p: _METRICS_TABLE)

    def _fake_run_statement(
        _client: object, statement: SqlStatement, _formatter: object, **kwargs: object
    ) -> None:
        captured["statement"] = statement

    monkeypatch.setattr(facets_module, "run_statement", _fake_run_statement)
    return captured


def test_stream_default_value_is_accepted(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["hosts"])
    assert result.exit_code == 0, result.stdout


def test_metrics_stream_queries_the_metrics_table(
    _no_real_connection: dict[str, object],
) -> None:
    result = runner.invoke(app, ["hosts", "--stream", "metrics"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "GROUP BY HostName" in statement.sql
    assert "TimeUnix" in statement.sql


def test_metrics_stream_rejects_log_only_filters(
    _no_real_connection: dict[str, object],
) -> None:
    result = runner.invoke(app, ["hosts", "--stream", "metrics", "--level", "error"])
    assert result.exit_code != 0, result.stdout


def test_unknown_stream_fails_with_config_error_before_any_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import clickhouse_tool.cli.commands.facets as facets_module

    called = {"connected": False}
    monkeypatch.setattr(
        facets_module.wiring, "load_profile", lambda *_a, **_k: called.__setitem__("connected", True)
    )
    result = runner.invoke(app, ["hosts", "--stream", "bogus"])
    assert result.exit_code != 0
    assert called["connected"] is False


def test_each_facet_verb_builds_its_own_field(_no_real_connection: dict[str, object]) -> None:
    runner.invoke(app, ["hosts"])
    hosts_statement = _no_real_connection["statement"]
    assert isinstance(hosts_statement, SqlStatement)
    assert "HostName" in hosts_statement.sql

    runner.invoke(app, ["services"])
    services_statement = _no_real_connection["statement"]
    assert isinstance(services_statement, SqlStatement)
    assert "ServiceName" in services_statement.sql


def test_shared_filter_flags_apply_identically_to_both_verbs(
    _no_real_connection: dict[str, object],
) -> None:
    runner.invoke(app, ["hosts", "--stream", "logs", "--namespace", "prod"])
    hosts_statement = _no_real_connection["statement"]
    assert isinstance(hosts_statement, SqlStatement)
    assert "prod" in hosts_statement.params.values()

    runner.invoke(app, ["services", "--stream", "logs", "--namespace", "prod"])
    services_statement = _no_real_connection["statement"]
    assert isinstance(services_statement, SqlStatement)
    assert "prod" in services_statement.params.values()


def test_humanize_last_seen_replaces_the_raw_datetime_column() -> None:
    columns = (ColumnMeta(name="host", ch_type="String"), ColumnMeta(name="last_seen", ch_type="DateTime"))
    rows = RowSet(columns=columns, rows=(("fw7", datetime.now(UTC) - timedelta(minutes=5)),), row_count=1)

    result = _humanize_last_seen(rows)

    assert result.columns == columns
    assert result.rows[0] == ("fw7", "5m ago")
