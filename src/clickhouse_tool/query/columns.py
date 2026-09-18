"""Column name mapping from short display names to ClickHouse expressions.

A column list becomes part of the SQL text; it cannot bind as a
parameter. Dict lookup is the injection defense: only names present
in COLUMN_MAP reach that text.
"""

from __future__ import annotations

from clickhouse_tool.core.errors import ConfigError

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
