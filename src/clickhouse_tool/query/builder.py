"""Pure functions turning an intent into a parameterized SqlStatement.

One builder per intent type. The count builder assembles its own
statement from the intent's filters instead of editing another
builder's rendered SQL.
"""

from __future__ import annotations

from dataclasses import replace

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.models import SqlStatement
from clickhouse_tool.query.columns import COLUMN_MAP, DEFAULT_LOG_COLS, validate_columns
from clickhouse_tool.query.intents import (
    CountIntent,
    FacetIntent,
    Filters,
    LiftIntent,
    ListIntent,
    LogsIntent,
    MetricQuery,
)
from clickhouse_tool.query.predicates import (
    build_search_predicate,
    container_predicate,
    host_predicate,
    level_predicate,
    metric_name_predicate,
    namespace_predicate,
    service_predicate,
    since_predicate,
    time_predicate,
)
from clickhouse_tool.query.sort import canonicalise_sort
from clickhouse_tool.query.tables import SYSTEM_TABLES, validate_table
from clickhouse_tool.query.timerange import parse_time_range

# 20 is a comfortable interactive page size for row output. FacetIntent.limit
# stays 200 (query/intents.py) -- a facet list is a distribution summary,
# not a page of rows, and the two are deliberately different (see test
# pinning it).
_DEFAULT_ROW_LIMIT = 20


def _assemble_predicates(filters: Filters) -> tuple[list[str], dict[str, object], dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {}
    meta: dict[str, object] = {}

    if filters.host is not None:
        predicate = host_predicate(filters.host)
        clauses.append(predicate.sql)
        params.update(predicate.params)
    if filters.service is not None:
        predicate = service_predicate(filters.service)
        clauses.append(predicate.sql)
        params.update(predicate.params)
    if filters.namespace is not None:
        predicate = namespace_predicate(filters.namespace)
        clauses.append(predicate.sql)
        params.update(predicate.params)
    if filters.container is not None:
        predicate = container_predicate(filters.container)
        clauses.append(predicate.sql)
        params.update(predicate.params)
        meta["container_preflight_required"] = True
    if filters.level is not None:
        predicate = level_predicate(filters.level)
        clauses.append(predicate.sql)
        params.update(predicate.params)
    if filters.time_range is not None:
        predicate = time_predicate(filters.time_range)
        clauses.append(predicate.sql)
        params.update(predicate.params)
    if filters.search is not None:
        predicate, strategy = build_search_predicate(filters.search)
        clauses.append(predicate.sql)
        params.update(predicate.params)
        meta["search_strategy"] = strategy

    return clauses, params, meta


def _where_clause(clauses: list[str]) -> str:
    if not clauses:
        return ""
    return " WHERE " + " AND ".join(clauses)


def _projection(columns: tuple[str, ...] | None, full: bool, raw: bool) -> str:
    if full or raw:
        return "*"
    names = validate_columns(columns or DEFAULT_LOG_COLS)
    return ", ".join(f"{COLUMN_MAP[name]} AS {name}" for name in names)


def build_logs(intent: LogsIntent, table: str) -> SqlStatement:
    clauses, params, meta = _assemble_predicates(intent.filters)
    projection = _projection(intent.columns, intent.full, intent.raw)
    sort_sql = canonicalise_sort(intent.sort)
    limit = intent.limit if intent.limit is not None else _DEFAULT_ROW_LIMIT

    # projection/sort come from COLUMN_MAP/SORT_ALIASES dict lookups, clauses
    # bind every user value as a parameter -- no raw user text reaches this f-string.
    sql = (
        f"SELECT {projection} FROM {table}{_where_clause(clauses)} "  # noqa: S608
        f"ORDER BY {sort_sql} LIMIT %(limit)s"
    )
    params["limit"] = limit
    if intent.full or intent.raw:
        meta["nested_output"] = True
    else:
        meta["column_names"] = validate_columns(intent.columns or DEFAULT_LOG_COLS)
        params["tz"] = intent.tz
    return SqlStatement(sql=sql, params=params, meta=meta)


_FOLLOW_BATCH_LIMIT = 5000
CURSOR_COLUMN = "__cursor_ts"


def build_logs_since(intent: LogsIntent, table: str, since: str) -> SqlStatement:
    """Poll variant of :func:`build_logs`: rows strictly after ``since``, oldest first.

    ``since`` and :data:`CURSOR_COLUMN` are full-precision strings.
    Python's ``datetime`` truncates ``DateTime64(9)``, re-matching the
    same row on the next poll.
    """
    static_filters = replace(intent.filters, time_range=None)
    clauses, params, meta = _assemble_predicates(static_filters)
    since_pred = since_predicate(since)
    clauses.append(since_pred.sql)
    params.update(since_pred.params)

    projection = _projection(intent.columns, intent.full, intent.raw)
    projection += f", toString(Timestamp) AS {CURSOR_COLUMN}"

    # projection/clauses bind every user value as a parameter or come from
    # dict lookups -- no raw user text reaches this f-string.
    sql = (
        f"SELECT {projection} FROM {table}{_where_clause(clauses)} "  # noqa: S608
        f"ORDER BY Timestamp ASC LIMIT %(limit)s"
    )
    params["limit"] = _FOLLOW_BATCH_LIMIT
    if intent.full or intent.raw:
        meta["nested_output"] = True
    else:
        meta["column_names"] = (
            *validate_columns(intent.columns or DEFAULT_LOG_COLS),
            CURSOR_COLUMN,
        )
        params["tz"] = intent.tz
    return SqlStatement(sql=sql, params=params, meta=meta)


def build_initial_cursor(window: str) -> SqlStatement:
    """A one-row probe for ``--follow``'s starting cursor, evaluated server-side.

    Full-precision string, matching :func:`build_logs_since` -- see its
    docstring for why a raw ``DateTime64(9)`` bound is unsafe here.
    """
    count, unit = parse_time_range(window)
    sql = f"SELECT toString(now() - INTERVAL %(n)s {unit}) AS cursor"
    return SqlStatement(sql=sql, params={"n": count})


def build_latest_cursor(intent: LogsIntent, table: str) -> SqlStatement:
    """``--follow``'s starting cursor: the matching table's most recent row.

    Skips ``time_range``/backlog; computed server-side. Empty when
    nothing matches -- caller falls back to :func:`build_initial_cursor`.
    """
    static_filters = replace(intent.filters, time_range=None)
    clauses, params, _meta = _assemble_predicates(static_filters)

    # clauses bind every user value as a parameter -- no raw user text reaches this f-string.
    sql = (
        f"SELECT toString(Timestamp) AS cursor FROM {table}"  # noqa: S608
        f"{_where_clause(clauses)} ORDER BY Timestamp DESC LIMIT 1"
    )
    return SqlStatement(sql=sql, params=params)


def build_count(intent: CountIntent, table: str) -> SqlStatement:
    clauses, params, meta = _assemble_predicates(intent.filters)
    # clauses bind every user value as a parameter; no raw user text here.
    sql = f"SELECT count() FROM {table}{_where_clause(clauses)}"  # noqa: S608
    return SqlStatement(sql=sql, params=params, meta=meta)


def build_facet(intent: FacetIntent, table: str) -> SqlStatement:
    if intent.facet_field not in ("host", "service"):
        raise ConfigError(f"unknown facet field '{intent.facet_field}'; accepted: host, service")
    group_col = "HostName" if intent.facet_field == "host" else "ServiceName"
    clauses, params, meta = _assemble_predicates(intent.filters)

    # group_col comes from the "host"/"service" branch above, clauses bind
    # every user value as a parameter -- no raw user text reaches this f-string.
    sql = (
        f"SELECT {group_col} AS {intent.facet_field}, count() AS count, "  # noqa: S608
        f"max(Timestamp) AS last_seen FROM {table}"
        f"{_where_clause(clauses)} GROUP BY {group_col} ORDER BY count DESC"
    )
    if not intent.unbounded:
        sql += " LIMIT %(limit)s"
        params["limit"] = intent.limit
    return SqlStatement(sql=sql, params=params, meta=meta)


_METRICS_UNSUPPORTED_FILTERS = ("namespace", "container", "level", "search")
_METRICS_FACET_COLUMNS = {"host": "HostName", "service": "ServiceName", "metric": "MetricName"}


def build_metrics_facet(intent: FacetIntent, table: str) -> SqlStatement:
    """Grouped count over the metrics stream's host, service, or metric name.

    Metrics carry no log-shaped attributes -- only the time filter
    applies; any other filter raises.
    """
    if intent.facet_field not in _METRICS_FACET_COLUMNS:
        accepted = ", ".join(_METRICS_FACET_COLUMNS)
        raise ConfigError(f"unknown facet field '{intent.facet_field}'; accepted: {accepted}")
    unsupported = [
        name for name in _METRICS_UNSUPPORTED_FILTERS if getattr(intent.filters, name) is not None
    ]
    if unsupported:
        raise ConfigError(
            f"--stream metrics does not support: {', '.join(unsupported)}"
        )
    group_col = _METRICS_FACET_COLUMNS[intent.facet_field]
    clauses: list[str] = []
    params: dict[str, object] = {}
    if intent.filters.time_range is not None:
        predicate = time_predicate(intent.filters.time_range, column="TimeUnix")
        clauses.append(predicate.sql)
        params.update(predicate.params)

    # group_col comes from the _METRICS_FACET_COLUMNS lookup above, clauses bind
    # every user value as a parameter -- no raw user text reaches this f-string.
    sql = (
        f"SELECT {group_col} AS {intent.facet_field}, count() AS count, "  # noqa: S608
        f"max(TimeUnix) AS last_seen FROM {table}"
        f"{_where_clause(clauses)} GROUP BY {group_col} ORDER BY count DESC"
    )
    if not intent.unbounded:
        sql += " LIMIT %(limit)s"
        params["limit"] = intent.limit
    return SqlStatement(sql=sql, params=params, meta={})


_DEFAULT_METRIC_VALUES_LIMIT = 1000
METRIC_CURSOR_COLUMN = "__cursor_ts"
_METRIC_VALUE_PROJECTION = "TimeUnix AS ts, HostName AS host, ServiceName AS service, MetricName AS metric, Value AS value"


def _metric_clauses(
    query: MetricQuery, *, include_time_range: bool = True
) -> tuple[list[str], dict[str, object]]:
    clauses: list[str] = []
    params: dict[str, object] = {}
    for predicate in (
        metric_name_predicate(query.name),
        *((host_predicate(query.host),) if query.host is not None else ()),
        *((service_predicate(query.service),) if query.service is not None else ()),
    ):
        clauses.append(predicate.sql)
        params.update(predicate.params)
    if include_time_range and query.time_range is not None:
        predicate = time_predicate(query.time_range, column="TimeUnix")
        clauses.append(predicate.sql)
        params.update(predicate.params)
    return clauses, params


_SPLIT_BY_COLUMNS = {"host": "HostName", "service": "ServiceName"}


def _split_by_projection(split_by: tuple[str, ...]) -> tuple[str, str]:
    """Validate ``split_by`` and render its SELECT/GROUP BY fragments.

    ``select_extra`` trails a ``", "`` when non-empty. ``group_by`` is
    the full grouping key, metric first; a caller's own trailing key
    (e.g. ``bucket``) is not included.
    """
    unknown = [name for name in split_by if name not in _SPLIT_BY_COLUMNS]
    if unknown:
        accepted = ", ".join(_SPLIT_BY_COLUMNS)
        raise ConfigError(f"unknown --split-by field(s) {', '.join(unknown)}; accepted: {accepted}")
    select_extra = "".join(f"{_SPLIT_BY_COLUMNS[name]} AS {name}, " for name in split_by)
    group_by = ", ".join(("MetricName", *(_SPLIT_BY_COLUMNS[name] for name in split_by)))
    return select_extra, group_by


def build_metric_status(query: MetricQuery, table: str, split_by: tuple[str, ...] = ()) -> SqlStatement:
    """Per-metric min/max/avg/stddev summary, one row per matched metric name.

    ``split_by`` (``"host"``, ``"service"``, or both) breaks each
    metric's summary out per host/service instead of merging them.
    """
    clauses, params = _metric_clauses(query)
    select_extra, group_by = _split_by_projection(split_by)

    # split_by is checked against _SPLIT_BY_COLUMNS above -- no raw user text reaches this f-string.
    sql = (
        f"SELECT MetricName AS metric, {select_extra}count() AS count, min(Value) AS min, "  # noqa: S608
        "max(Value) AS max, avg(Value) AS avg, stddevPop(Value) AS stddev "
        f"FROM {table}{_where_clause(clauses)} GROUP BY {group_by} ORDER BY {group_by}"
    )
    return SqlStatement(sql=sql, params=params)


def build_metric_values(query: MetricQuery, table: str, limit: int | None = None) -> SqlStatement:
    """Raw datapoints for a metric (or stem), oldest first."""
    clauses, params = _metric_clauses(query)
    sql = (
        f"SELECT {_METRIC_VALUE_PROJECTION} FROM {table}"  # noqa: S608
        f"{_where_clause(clauses)} ORDER BY TimeUnix ASC LIMIT %(limit)s"
    )
    params["limit"] = limit if limit is not None else _DEFAULT_METRIC_VALUES_LIMIT
    return SqlStatement(sql=sql, params=params)


def build_metric_values_since(query: MetricQuery, table: str, since: str) -> SqlStatement:
    """Poll variant of :func:`build_metric_values` for ``metrics values --follow``.

    Mirrors :func:`build_logs_since`'s full-precision string cursor.
    """
    clauses, params = _metric_clauses(query, include_time_range=False)
    since_pred = since_predicate(since, column="TimeUnix")
    clauses.append(since_pred.sql)
    params.update(since_pred.params)

    projection = f"{_METRIC_VALUE_PROJECTION}, toString(TimeUnix) AS {METRIC_CURSOR_COLUMN}"
    sql = (
        f"SELECT {projection} FROM {table}"  # noqa: S608
        f"{_where_clause(clauses)} ORDER BY TimeUnix ASC LIMIT %(limit)s"
    )
    params["limit"] = _FOLLOW_BATCH_LIMIT
    return SqlStatement(sql=sql, params=params)


def build_latest_metric_cursor(query: MetricQuery, table: str) -> SqlStatement:
    """``metrics values --follow``'s starting cursor: the matched metric's most recent row."""
    clauses, params = _metric_clauses(query, include_time_range=False)
    sql = (
        "SELECT toString(TimeUnix) AS cursor "  # noqa: S608
        f"FROM {table}{_where_clause(clauses)} ORDER BY TimeUnix DESC LIMIT 1"
    )
    return SqlStatement(sql=sql, params=params)


def build_metric_histogram(
    query: MetricQuery, table: str, bucket: str, split_by: tuple[str, ...] = ()
) -> SqlStatement:
    """Time-bucketed min/max/avg/count per matched metric name.

    ``split_by`` (``"host"``, ``"service"``, or both) breaks each
    metric's buckets out per host/service instead of merging them.
    """
    clauses, params = _metric_clauses(query)
    bucket_count, bucket_unit = parse_time_range(bucket)
    params["bucket_n"] = bucket_count
    select_extra, group_by = _split_by_projection(split_by)

    # split_by is checked against _SPLIT_BY_COLUMNS above -- no raw user text reaches this f-string.
    sql = (
        f"SELECT MetricName AS metric, {select_extra}"  # noqa: S608
        f"toStartOfInterval(TimeUnix, INTERVAL %(bucket_n)s {bucket_unit}) AS bucket, "
        "min(Value) AS min, max(Value) AS max, avg(Value) AS avg, count() AS count "
        f"FROM {table}{_where_clause(clauses)} "
        f"GROUP BY {group_by}, bucket ORDER BY {group_by}, bucket"
    )
    return SqlStatement(sql=sql, params=params)


def build_list(intent: ListIntent) -> SqlStatement:
    table = validate_table(intent.table)
    projection = "*" if intent.columns is None else ", ".join(intent.columns)
    params: dict[str, object] = {}
    # table is gated by validate_table's allow-list above.
    sql = f"SELECT {projection} FROM {table}"  # noqa: S608
    if intent.limit is not None:
        sql += " LIMIT %(limit)s"
        params["limit"] = intent.limit
    return SqlStatement(sql=sql, params=params, meta={})


def build_lift(intent: LiftIntent) -> SqlStatement:
    table = validate_table(intent.table)
    database, _, table_name = table.partition(".")
    sql = "SELECT name, type FROM system.columns WHERE database = %(database)s AND table = %(table)s"
    return SqlStatement(
        sql=sql, params={"database": database, "table": table_name}, meta={}
    )


def build_tables_list(database: str) -> SqlStatement:
    """Every table `list`/`lift`/`query` may target: the profile's `otel.*` plus system tables.

    System table names come from :data:`SYSTEM_TABLES`, this module's own
    fixed allow-list, not user input.
    """
    system_names = ", ".join(f"'{name.partition('.')[2]}'" for name in sorted(SYSTEM_TABLES))
    sql = (
        "SELECT concat(database, '.', name) AS table FROM system.tables "  # noqa: S608
        f"WHERE database = %(database)s OR (database = 'system' AND name IN ({system_names})) "
        "ORDER BY table"
    )
    return SqlStatement(sql=sql, params={"database": database}, meta={})


def build_container_preflight(container: str, table: str) -> SqlStatement:
    """Fixed 24h-lookback existence check for a container-scoped query.

    Returns both an existence signal and the key's most recent occurrence,
    so the CLI can warn before returning zero rows silently.
    """
    predicate = container_predicate(container)
    # predicate.sql binds the container value as a parameter, not raw text.
    sql = (
        "SELECT count() > 0 AS key_exists, max(Timestamp) AS last_seen "  # noqa: S608
        f"FROM {table} WHERE {predicate.sql} "
        "AND Timestamp >= now() - INTERVAL 24 HOUR"
    )
    return SqlStatement(sql=sql, params=predicate.params, meta={"kind": "container_preflight"})
