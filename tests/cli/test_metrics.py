"""Tests for the `metrics` verb group: names, status, values, histogram."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli.main import app
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.core.models import RowSet, SqlStatement

pytestmark = pytest.mark.unit

runner = CliRunner()
_METRICS_TABLE = "otel.otel_metrics_gauge"


@pytest.fixture(autouse=True)
def _no_real_connection(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    import clickhouse_tool.cli.commands.facets as facets_module
    import clickhouse_tool.cli.commands.metrics as metrics_module

    captured: dict[str, object] = {}

    def _fake_load_profile(_profile: str | None, **_kwargs: object) -> ResolvedProfile:
        return ResolvedProfile()

    def _fake_open_client(_profile: ResolvedProfile) -> object:
        return object()

    def _fake_run_statement(
        _client: object, statement: SqlStatement, formatter: object, **kwargs: object
    ) -> None:
        captured["statement"] = statement
        captured["formatter"] = formatter

    for module in (facets_module, metrics_module):
        monkeypatch.setattr(module.wiring, "load_profile", _fake_load_profile)
        monkeypatch.setattr(module.wiring, "open_client", _fake_open_client)
    monkeypatch.setattr(facets_module.wiring, "resolve_metrics_table", lambda _p: _METRICS_TABLE)
    monkeypatch.setattr(metrics_module.wiring, "resolve_metrics_table", lambda _p: _METRICS_TABLE)
    monkeypatch.setattr(facets_module, "run_statement", _fake_run_statement)
    monkeypatch.setattr(metrics_module, "run_statement", _fake_run_statement)
    return captured


def test_names_lists_metric_names(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["metrics", "names"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "GROUP BY MetricName" in statement.sql


def test_bare_metrics_defaults_to_names(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["metrics"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "GROUP BY MetricName" in statement.sql


def test_status_reports_summary_stats_for_a_name(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["metrics", "status", "k8s.node.memory"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "stddevPop(Value)" in statement.sql
    assert "k8s.node.memory" in statement.params.values()


def test_status_split_by_parses_a_comma_separated_list(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["metrics", "status", "k8s.node.memory", "--split-by", "host,service"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "GROUP BY MetricName, HostName, ServiceName" in statement.sql


def test_values_returns_raw_datapoints(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["metrics", "values", "k8s.node.memory.usage"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "ORDER BY TimeUnix ASC" in statement.sql


def test_values_follow_rejects_explicit_limit(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["metrics", "values", "k8s.node.memory.usage", "--follow", "-n", "10"])
    assert result.exit_code != 0


def test_values_follow_seeds_from_the_latest_matching_datapoint(
    monkeypatch: pytest.MonkeyPatch, _no_real_connection: dict[str, object]
) -> None:
    import clickhouse_tool.cli.commands.metrics as metrics_module

    class _FakeClient:
        def execute(self, statement: SqlStatement) -> RowSet:
            assert "ORDER BY TimeUnix DESC LIMIT 1" in statement.sql
            return RowSet(columns=(), rows=(("2026-01-01 00:00:00.123456789",),), row_count=1)

        def close(self) -> None:
            pass

    monkeypatch.setattr(metrics_module.wiring, "open_client", lambda _p: _FakeClient())

    seeds: dict[str, object] = {}

    def _fake_run_metric_follow(_client: object, *, since: str, **_kwargs: object) -> None:
        seeds["since"] = since

    monkeypatch.setattr(metrics_module, "run_metric_follow", _fake_run_metric_follow)

    result = runner.invoke(app, ["metrics", "values", "k8s.node.memory.usage", "--follow"])

    assert result.exit_code == 0, result.stdout
    assert seeds["since"] == "2026-01-01 00:00:00.123456789"


def test_histogram_defaults_bucket_size_to_the_time_window(
    _no_real_connection: dict[str, object],
) -> None:
    result = runner.invoke(app, ["metrics", "histogram", "k8s.node.memory.usage", "-t", "1h"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "INTERVAL %(bucket_n)s MINUTE" in statement.sql
    assert statement.params["bucket_n"] == 5


def test_values_table_output_uses_second_precision_for_a_short_window(
    _no_real_connection: dict[str, object],
) -> None:
    from clickhouse_tool.formatters.table import TableFormatter

    result = runner.invoke(app, ["metrics", "values", "system.cpu.utilization", "-t", "15m", "-f", "table"])
    assert result.exit_code == 0, result.stdout
    formatter = _no_real_connection["formatter"]
    assert isinstance(formatter, TableFormatter)
    assert formatter._ts_precision == "s"


def test_values_table_output_drops_to_minute_precision_for_a_long_window(
    _no_real_connection: dict[str, object],
) -> None:
    from clickhouse_tool.formatters.table import TableFormatter

    result = runner.invoke(app, ["metrics", "values", "system.cpu.utilization", "-t", "24h", "-f", "table"])
    assert result.exit_code == 0, result.stdout
    formatter = _no_real_connection["formatter"]
    assert isinstance(formatter, TableFormatter)
    assert formatter._ts_precision == "m"


def test_values_explicit_ts_decimals_forces_second_precision_even_for_a_long_window(
    _no_real_connection: dict[str, object],
) -> None:
    from clickhouse_tool.formatters.table import TableFormatter

    result = runner.invoke(
        app,
        ["metrics", "values", "system.cpu.utilization", "-t", "24h", "-f", "table", "--ts-decimals", "3"],
    )
    assert result.exit_code == 0, result.stdout
    formatter = _no_real_connection["formatter"]
    assert isinstance(formatter, TableFormatter)
    assert formatter._ts_precision == "s"
    assert formatter._ts_decimals == 3


def test_histogram_honours_an_explicit_bucket_override(
    _no_real_connection: dict[str, object],
) -> None:
    result = runner.invoke(
        app, ["metrics", "histogram", "k8s.node.memory.usage", "-t", "1h", "--bucket", "1m"]
    )
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert statement.params["bucket_n"] == 1


def test_histogram_split_by_parses_a_comma_separated_list(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(
        app, ["metrics", "histogram", "k8s.node.memory.usage", "-t", "1h", "--split-by", "host,service"]
    )
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "GROUP BY MetricName, HostName, ServiceName, bucket" in statement.sql


def test_histogram_without_split_by_groups_on_metric_and_bucket_only(
    _no_real_connection: dict[str, object],
) -> None:
    result = runner.invoke(app, ["metrics", "histogram", "k8s.node.memory.usage", "-t", "1h"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert "GROUP BY MetricName, bucket" in statement.sql
