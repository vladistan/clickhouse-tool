"""The one shared execute step used by every data verb.

Verb modules stay glue: no SQL text, no retry logic, no error tables.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator

from clickhouse_tool.core.client.base import ChClient
from clickhouse_tool.core.errors import UnsupportedFilterError
from clickhouse_tool.core.models import ColumnMeta, RowSet, SqlStatement
from clickhouse_tool.formatters import Formatter
from clickhouse_tool.query.builder import (
    CURSOR_COLUMN,
    METRIC_CURSOR_COLUMN,
    build_container_preflight,
    build_logs_since,
    build_metric_values_since,
)
from clickhouse_tool.query.intents import LogsIntent, MetricQuery


def run_statement(
    client: ChClient,
    statement: SqlStatement,
    formatter: Formatter,
    *,
    table: str | None = None,
    row_transform: Callable[[RowSet], RowSet] | None = None,
) -> None:
    """Run the preflight decision if asked for, then render ``statement`` to stdout.

    ``row_transform`` rewrites the buffered result before formatting,
    never the streaming path. Closes ``client`` on every exit path.
    """
    try:
        if statement.meta.get("container_preflight_required"):
            _run_container_preflight(client, statement, table)
        if formatter.streaming:
            for line in formatter.format_stream(_stream_blocks(client, statement)):
                print(line)
        else:
            rows = client.execute(statement)
            if row_transform is not None:
                rows = row_transform(rows)
            for line in formatter.format(rows):
                print(line)
    finally:
        client.close()


def _run_container_preflight(client: ChClient, statement: SqlStatement, table: str | None) -> None:
    container = statement.params.get("container")
    if container is None or table is None:
        return
    preflight = build_container_preflight(str(container), table)
    result = client.execute(preflight)
    key_exists = bool(result.rows[0][0]) if result.rows else False
    if not key_exists:
        raise UnsupportedFilterError(f"container key '{container}' not found in the last 24h")


def _stream_blocks(client: ChClient, statement: SqlStatement) -> Iterator[RowSet]:
    """Wrap each streamed row in its own one-row RowSet.

    Names come from ``statement.meta["column_names"]`` when known
    statically; a wide (``--full``/``--raw``) projection has none, so
    positional placeholders take their place.
    """
    column_names = statement.meta.get("column_names")
    for row in client.stream(statement):
        names = column_names if column_names is not None else tuple(f"col{i}" for i in range(len(row)))
        columns = tuple(ColumnMeta(name=name, ch_type="") for name in names)
        yield RowSet(columns=columns, rows=(row,), row_count=1)


def run_follow(
    client: ChClient,
    *,
    intent: LogsIntent,
    table: str,
    formatter: Formatter,
    since: str,
    poll_interval: float = 2.0,
) -> None:
    """Poll for new rows after ``since`` and print each new batch as it arrives.

    Runs until interrupted; a caller's own funnel handles ``KeyboardInterrupt``.
    Never buffers more than one poll's batch in memory.
    """
    try:
        cursor = since
        statement = build_logs_since(intent, table, cursor)
        if statement.meta.get("container_preflight_required"):
            _run_container_preflight(client, statement, table)
        while True:
            rows = client.execute(statement)
            if rows.row_count:
                cursor, visible = _advance_cursor(rows)
                for line in formatter.format(visible):
                    print(line)
            time.sleep(poll_interval)
            statement = build_logs_since(intent, table, cursor)
    finally:
        client.close()


def _advance_cursor(rows: RowSet, cursor_column: str = CURSOR_COLUMN) -> tuple[str, RowSet]:
    """Read the full-precision cursor off the last row, then strip that column."""
    idx = next(i for i, col in enumerate(rows.columns) if col.name == cursor_column)
    cursor = str(rows.rows[-1][idx])
    visible_columns = tuple(col for col in rows.columns if col.name != cursor_column)
    visible_rows = tuple(row[:idx] + row[idx + 1 :] for row in rows.rows)
    return cursor, RowSet(columns=visible_columns, rows=visible_rows, row_count=rows.row_count)


def run_metric_follow(
    client: ChClient,
    *,
    query: MetricQuery,
    table: str,
    formatter: Formatter,
    since: str,
    poll_interval: float = 2.0,
) -> None:
    """Poll for new metric datapoints after ``since``, oldest first. See :func:`run_follow`."""
    try:
        cursor = since
        statement = build_metric_values_since(query, table, cursor)
        while True:
            rows = client.execute(statement)
            if rows.row_count:
                cursor, visible = _advance_cursor(rows, METRIC_CURSOR_COLUMN)
                for line in formatter.format(visible):
                    print(line)
            time.sleep(poll_interval)
            statement = build_metric_values_since(query, table, cursor)
    finally:
        client.close()
