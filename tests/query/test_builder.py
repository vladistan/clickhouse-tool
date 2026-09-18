"""Tests for statement builders: intent in, SqlStatement out."""

import pytest

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.query.builder import (
    CURSOR_COLUMN,
    build_container_preflight,
    build_count,
    build_facet,
    build_initial_cursor,
    build_latest_cursor,
    build_latest_metric_cursor,
    build_lift,
    build_list,
    build_logs,
    build_logs_since,
    build_metric_histogram,
    build_metric_status,
    build_metric_values,
    build_metric_values_since,
    build_metrics_facet,
    build_tables_list,
)
from clickhouse_tool.query.intents import (
    CountIntent,
    FacetIntent,
    Filters,
    LiftIntent,
    ListIntent,
    LogsIntent,
    MetricQuery,
)
from clickhouse_tool.query.tables import SYSTEM_TABLES

pytestmark = pytest.mark.unit

_TABLE = "otel.otel_logs"


def test_logs_intent_produces_statement_with_no_user_values_in_sql() -> None:
    filters = Filters(
        host="firewall7",
        service="api",
        namespace="prod",
        search="refused",
        level="warn",
        time_range="15m",
    )
    intent = LogsIntent(filters=filters)

    statement = build_logs(intent, _TABLE)

    for value in statement.params.values():
        if isinstance(value, str):
            assert value not in statement.sql
    assert "firewall7" in statement.params.values()
    assert "api" in statement.params.values()


def test_logs_default_page_is_twenty_rows() -> None:
    intent = LogsIntent(filters=Filters(host="firewall7"))

    statement = build_logs(intent, _TABLE)

    assert statement.params["limit"] == 20


def test_logs_explicit_size_overrides_the_default() -> None:
    intent = LogsIntent(filters=Filters(host="firewall7"), limit=500)

    statement = build_logs(intent, _TABLE)

    assert statement.params["limit"] == 500


def test_logs_since_orders_ascending_and_binds_the_cursor() -> None:
    intent = LogsIntent(filters=Filters(host="firewall7", time_range="15m"))

    statement = build_logs_since(intent, _TABLE, since="2026-01-01 00:00:00")

    assert "ORDER BY Timestamp ASC" in statement.sql
    assert "Timestamp > %(since)s" in statement.sql
    assert statement.params["since"] == "2026-01-01 00:00:00"
    # the window filter is replaced by the since-cursor, not layered on top
    assert "INTERVAL" not in statement.sql


def test_logs_since_carries_a_full_precision_hidden_cursor_column_for_narrow_projections() -> None:
    intent = LogsIntent(filters=Filters())

    statement = build_logs_since(intent, _TABLE, since="2026-01-01 00:00:00")

    assert f"toString(Timestamp) AS {CURSOR_COLUMN}" in statement.sql
    assert statement.meta["column_names"][-1] == CURSOR_COLUMN


def test_logs_since_wide_projection_also_carries_the_hidden_cursor_column() -> None:
    """DateTime64(9) through Python's datetime loses precision, so
    --full needs the string cursor too, not its own Timestamp column."""
    intent = LogsIntent(filters=Filters(), full=True)

    statement = build_logs_since(intent, _TABLE, since="2026-01-01 00:00:00")

    assert f"toString(Timestamp) AS {CURSOR_COLUMN}" in statement.sql
    assert statement.meta["nested_output"] is True


def test_initial_cursor_is_a_full_precision_server_side_probe() -> None:
    statement = build_initial_cursor("15m")

    assert statement.sql == "SELECT toString(now() - INTERVAL %(n)s MINUTE) AS cursor"
    assert statement.params == {"n": 15}


def test_latest_cursor_ignores_time_range_and_orders_by_timestamp_desc() -> None:
    intent = LogsIntent(filters=Filters(host="fw7", time_range="15m"))

    statement = build_latest_cursor(intent, _TABLE)

    assert "toString(Timestamp) AS cursor" in statement.sql
    assert "ORDER BY Timestamp DESC LIMIT 1" in statement.sql
    assert "fw7" in statement.params.values()
    assert "n" not in statement.params


def test_facet_intent_limit_default_is_two_hundred_by_deliberate_user_decision() -> None:
    """FacetIntent.limit stays 200: a distribution summary, not a page
    of rows. Do not unify it with the logs default of 20."""
    intent = FacetIntent(facet_field="host")

    assert intent.limit == 200


def test_count_intent_has_no_order_by_and_no_limit() -> None:
    logs_intent = LogsIntent(filters=Filters(host="firewall7"))
    count_intent = CountIntent.from_logs_intent(logs_intent)

    statement = build_count(count_intent, _TABLE)

    assert "ORDER BY" not in statement.sql
    assert "LIMIT" not in statement.sql
    assert "count()" in statement.sql


def test_count_intent_is_built_not_rewritten_from_logs_sql() -> None:
    logs_intent = LogsIntent(filters=Filters(host="firewall7"), sort="ts:desc", limit=10)
    count_intent = CountIntent.from_logs_intent(logs_intent)

    logs_statement = build_logs(logs_intent, _TABLE)
    count_statement = build_count(count_intent, _TABLE)

    assert count_statement.sql != logs_statement.sql
    assert "SELECT count()" in count_statement.sql


def test_facet_intent_produces_grouped_shape_with_default_cap() -> None:
    intent = FacetIntent(facet_field="host", filters=Filters(service="api"))

    statement = build_facet(intent, _TABLE)

    assert "GROUP BY HostName" in statement.sql
    assert "max(Timestamp) AS last_seen" in statement.sql
    assert statement.params["limit"] == 200


def test_facet_intent_honours_a_limit_override() -> None:
    intent = FacetIntent(facet_field="service", limit=50)

    statement = build_facet(intent, _TABLE)

    assert statement.params["limit"] == 50


def test_facet_intent_honours_unbounded() -> None:
    intent = FacetIntent(facet_field="host", unbounded=True)

    statement = build_facet(intent, _TABLE)

    assert "LIMIT" not in statement.sql
    assert "limit" not in statement.params


def test_facet_intent_rejects_unknown_field() -> None:
    intent = FacetIntent(facet_field="pod")
    with pytest.raises(ConfigError):
        build_facet(intent, _TABLE)


_METRICS_TABLE = "otel.otel_metrics_gauge"


def test_metrics_facet_groups_by_host_and_filters_on_time_unix() -> None:
    intent = FacetIntent(facet_field="host", filters=Filters(time_range="1h"))

    statement = build_metrics_facet(intent, _METRICS_TABLE)

    assert "GROUP BY HostName" in statement.sql
    assert "TimeUnix" in statement.sql
    assert "Timestamp" not in statement.sql
    assert "max(TimeUnix) AS last_seen" in statement.sql
    assert statement.params["limit"] == 200


def test_metrics_facet_groups_by_service() -> None:
    intent = FacetIntent(facet_field="service")

    statement = build_metrics_facet(intent, _METRICS_TABLE)

    assert "GROUP BY ServiceName" in statement.sql


def test_metrics_facet_honours_unbounded() -> None:
    intent = FacetIntent(facet_field="host", unbounded=True)

    statement = build_metrics_facet(intent, _METRICS_TABLE)

    assert "LIMIT" not in statement.sql


def test_metrics_facet_rejects_unknown_field() -> None:
    intent = FacetIntent(facet_field="pod")
    with pytest.raises(ConfigError):
        build_metrics_facet(intent, _METRICS_TABLE)


@pytest.mark.parametrize("field_name", ["namespace", "container", "level", "search"])
def test_metrics_facet_rejects_log_only_filters(field_name: str) -> None:
    intent = FacetIntent(facet_field="host", filters=Filters(**{field_name: "x"}))
    with pytest.raises(ConfigError):
        build_metrics_facet(intent, _METRICS_TABLE)


def test_metrics_facet_groups_by_metric_name() -> None:
    intent = FacetIntent(facet_field="metric")

    statement = build_metrics_facet(intent, _METRICS_TABLE)

    assert "GROUP BY MetricName" in statement.sql
    assert "SELECT MetricName AS metric" in statement.sql


def test_metric_status_groups_by_name_with_summary_stats() -> None:
    query = MetricQuery(name="k8s.node.memory", time_range="1h")

    statement = build_metric_status(query, _METRICS_TABLE)

    assert "startsWith(MetricName, %(name)s)" in statement.sql
    assert "stddevPop(Value) AS stddev" in statement.sql
    assert "GROUP BY MetricName" in statement.sql
    assert statement.params["name"] == "k8s.node.memory"


def test_metric_status_splits_by_host_and_service_when_asked() -> None:
    query = MetricQuery(name="k8s.node.memory", time_range="1h")

    statement = build_metric_status(query, _METRICS_TABLE, split_by=("host", "service"))

    assert "SELECT MetricName AS metric, HostName AS host, ServiceName AS service, count()" in statement.sql
    assert "GROUP BY MetricName, HostName, ServiceName" in statement.sql
    assert "ORDER BY MetricName, HostName, ServiceName" in statement.sql


def test_metric_status_rejects_an_unknown_split_by_field() -> None:
    query = MetricQuery(name="k8s.node.memory", time_range="1h")
    with pytest.raises(ConfigError):
        build_metric_status(query, _METRICS_TABLE, split_by=("pod",))


def test_metric_values_orders_oldest_first_with_a_default_limit() -> None:
    query = MetricQuery(name="k8s.node.filesystem.capacity", host="fw7")

    statement = build_metric_values(query, _METRICS_TABLE)

    assert "ORDER BY TimeUnix ASC LIMIT %(limit)s" in statement.sql
    assert statement.params["host"] == "fw7"
    assert statement.params["limit"] == 1000


def test_metric_values_honours_an_explicit_limit() -> None:
    query = MetricQuery(name="k8s.node.filesystem.capacity")

    statement = build_metric_values(query, _METRICS_TABLE, limit=5)

    assert statement.params["limit"] == 5


def test_metric_values_since_binds_a_full_precision_string_cursor() -> None:
    query = MetricQuery(name="k8s.node.memory")

    statement = build_metric_values_since(query, _METRICS_TABLE, since="2026-01-01 00:00:00.123456789")

    assert "TimeUnix > %(since)s" in statement.sql
    assert statement.params["since"] == "2026-01-01 00:00:00.123456789"
    assert "n" not in statement.params  # time_range dropped in the since variant


def test_latest_metric_cursor_ignores_time_range_and_orders_desc() -> None:
    query = MetricQuery(name="k8s.node.memory", time_range="15m")

    statement = build_latest_metric_cursor(query, _METRICS_TABLE)

    assert "ORDER BY TimeUnix DESC LIMIT 1" in statement.sql
    assert "n" not in statement.params


def test_metric_histogram_buckets_by_the_given_width() -> None:
    query = MetricQuery(name="k8s.node.memory", time_range="1h")

    statement = build_metric_histogram(query, _METRICS_TABLE, "5m")

    assert "toStartOfInterval(TimeUnix, INTERVAL %(bucket_n)s MINUTE)" in statement.sql
    assert statement.params["bucket_n"] == 5
    assert "GROUP BY MetricName, bucket" in statement.sql


def test_metric_histogram_splits_by_host_and_service_when_asked() -> None:
    query = MetricQuery(name="k8s.node.memory", time_range="1h")

    statement = build_metric_histogram(query, _METRICS_TABLE, "5m", split_by=("host", "service"))

    assert "SELECT MetricName AS metric, HostName AS host, ServiceName AS service, " in statement.sql
    assert "GROUP BY MetricName, HostName, ServiceName, bucket" in statement.sql
    assert "ORDER BY MetricName, HostName, ServiceName, bucket" in statement.sql


def test_metric_histogram_splits_by_a_single_field() -> None:
    query = MetricQuery(name="k8s.node.memory", time_range="1h")

    statement = build_metric_histogram(query, _METRICS_TABLE, "5m", split_by=("service",))

    assert "ServiceName AS service" in statement.sql
    assert "GROUP BY MetricName, ServiceName, bucket" in statement.sql


def test_metric_histogram_rejects_an_unknown_split_by_field() -> None:
    query = MetricQuery(name="k8s.node.memory", time_range="1h")
    with pytest.raises(ConfigError):
        build_metric_histogram(query, _METRICS_TABLE, "5m", split_by=("pod",))


def test_container_preflight_is_fixed_24h_lookback_with_existence_and_last_seen() -> None:
    statement = build_container_preflight("nginx", _TABLE)

    assert "24 HOUR" in statement.sql
    assert "key_exists" in statement.sql
    assert "last_seen" in statement.sql
    assert "nginx" in statement.params.values()


def test_full_and_raw_produce_full_projection_and_mark_nested_output() -> None:
    full_statement = build_logs(LogsIntent(full=True), _TABLE)
    raw_statement = build_logs(LogsIntent(raw=True), _TABLE)

    assert "SELECT *" in full_statement.sql
    assert full_statement.meta["nested_output"] is True
    assert "SELECT *" in raw_statement.sql
    assert raw_statement.meta["nested_output"] is True


def test_default_projection_uses_default_columns() -> None:
    statement = build_logs(LogsIntent(), _TABLE)
    assert "AS ts" in statement.sql
    assert "AS msg" in statement.sql
    assert statement.meta["column_names"] == ("ts", "level", "host", "service", "msg")


def test_container_filter_signals_preflight_required() -> None:
    intent = LogsIntent(filters=Filters(container="nginx"))
    statement = build_logs(intent, _TABLE)
    assert statement.meta["container_preflight_required"] is True


def test_list_intent_uses_allow_listed_table() -> None:
    statement = build_list(ListIntent(table="system.parts", limit=10))
    assert "FROM system.parts" in statement.sql
    assert statement.params["limit"] == 10


def test_list_intent_with_no_limit_omits_limit_clause() -> None:
    statement = build_list(ListIntent(table="system.parts"))
    assert "LIMIT" not in statement.sql
    assert "limit" not in statement.params


def test_list_intent_rejects_non_allow_listed_table() -> None:
    with pytest.raises(ConfigError):
        build_list(ListIntent(table="system.users"))


def test_lift_intent_queries_column_metadata_with_bound_table_name() -> None:
    statement = build_lift(LiftIntent(table="otel.logs"))
    assert "system.columns" in statement.sql
    assert statement.params["database"] == "otel"
    assert statement.params["table"] == "logs"
    assert "otel.logs" not in statement.sql


def test_tables_list_binds_the_database_and_names_every_system_table() -> None:
    statement = build_tables_list("otel")
    assert statement.params["database"] == "otel"
    assert "%(database)s" in statement.sql
    for table in SYSTEM_TABLES:
        assert table.partition(".")[2] in statement.sql


def test_logs_binds_the_intent_timezone_for_narrow_projection() -> None:
    intent = LogsIntent(filters=Filters(host="firewall7"), tz="America/New_York")
    statement = build_logs(intent, _TABLE)
    assert statement.params["tz"] == "America/New_York"
    assert "%(tz)s" in statement.sql


def test_logs_wide_projection_has_no_timezone_param() -> None:
    """--full/--raw select * directly; the ts alias (and its tz arg) never appears."""
    intent = LogsIntent(filters=Filters(), full=True, tz="America/New_York")
    statement = build_logs(intent, _TABLE)
    assert "tz" not in statement.params


def test_logs_since_binds_the_intent_timezone_for_narrow_projection() -> None:
    intent = LogsIntent(filters=Filters(), tz="Europe/Berlin")
    statement = build_logs_since(intent, _TABLE, since="2026-01-01 00:00:00")
    assert statement.params["tz"] == "Europe/Berlin"
