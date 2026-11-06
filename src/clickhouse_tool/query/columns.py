"""Column name mapping from short display names to ClickHouse expressions.

A column list becomes part of the SQL text; it cannot bind as a
parameter. Dict lookup is the injection defense: only names present
in COLUMN_MAP reach that text.
"""

from __future__ import annotations

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.models import ColumnMeta, RowSet

COLUMN_MAP: dict[str, str] = {
    "ts": "formatDateTime(Timestamp, '%Y-%m-%d %H:%i:%S', %(tz)s)",
    "level": "SeverityText",
    "host": "HostName",
    "service": "ServiceName",
    "msg": "Body",
    # TraceId is empty on most rows in practice, so it is not a usable row
    # identifier. A deterministic hash over columns that vary per row
    # stands in instead -- stable for a given row, distinct across rows
    # that differ in timestamp, service, host, or message.
    "id": "hex(cityHash64(Timestamp, ServiceName, HostName, Body))",
}

DEFAULT_LOG_COLS: tuple[str, ...] = ("ts", "level", "host", "service", "msg")


def validate_columns(names: tuple[str, ...]) -> tuple[str, ...]:
    """Reject any column name outside COLUMN_MAP, listing accepted names."""
    unknown = [name for name in names if name not in COLUMN_MAP]
    if unknown:
        accepted = ", ".join(sorted(COLUMN_MAP))
        raise ConfigError(f"unknown column(s) {', '.join(unknown)}; accepted: {accepted}")
    return names


LAG_COLUMN = "__lag_s"
LAG_FIELD = "lag_s"

# Seconds between the event time and the insert time, positive when the
# row arrived late. Without InsertedAt only a future-stamped row can be
# told apart, measured against query time.
LAG_WITH_INSERTED_AT = f"dateDiff('second', Timestamp, InsertedAt) AS {LAG_COLUMN}"
LAG_WITHOUT_INSERTED_AT = f"dateDiff('second', Timestamp, now()) AS {LAG_COLUMN}"


def lag_expression(has_inserted_at: bool) -> str:
    return LAG_WITH_INSERTED_AT if has_inserted_at else LAG_WITHOUT_INSERTED_AT


def classify_lag(lag_s: int, late_after_s: int, future_after_s: int) -> str | None:
    """``late``, ``future`` or ``None`` for one row's lag in seconds."""
    if lag_s > late_after_s:
        return "late"
    if -lag_s > future_after_s:
        return "future"
    return None


def apply_lag_column(rows: RowSet, late_after_s: int, future_after_s: int) -> RowSet:
    """Turn the hidden lag column into ``lag_s``: the lag on flagged rows, else None."""
    names = [column.name for column in rows.columns]
    if LAG_COLUMN not in names:
        return rows
    idx = names.index(LAG_COLUMN)
    columns = list(rows.columns)
    columns[idx] = ColumnMeta(name=LAG_FIELD, ch_type="Nullable(Int64)")
    out = []
    for row in rows.rows:
        lag = int(row[idx])
        flagged = classify_lag(lag, late_after_s, future_after_s) is not None
        out.append((*row[:idx], lag if flagged else None, *row[idx + 1 :]))
    return RowSet(
        columns=tuple(columns), rows=tuple(out), row_count=rows.row_count, truncated=rows.truncated
    )


def layout_hidden_columns(has_namespace: bool) -> tuple[tuple[str, str], ...]:
    """Hidden columns the one-line layout reads: severity number and source facts."""
    columns: list[tuple[str, str]] = [("SeverityNumber", "__sev")]
    if has_namespace:
        columns.append(("Namespace", "__ns"))
    columns.append(("LogAttributes['log.source']", "__src"))
    columns.append(("ResourceAttributes['container.name']", "__ctr"))
    return tuple(columns)
