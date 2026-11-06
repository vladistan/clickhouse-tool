"""The one shared execute step used by every data verb.

Verb modules stay glue: no SQL text, no retry logic, no error tables.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable, Iterable, Iterator

from clickhouse_tool.core.client.base import ChClient
from clickhouse_tool.core.errors import UnsupportedFilterError
from clickhouse_tool.core.models import ColumnMeta, RowSet, SqlStatement
from clickhouse_tool.formatters import Formatter
from clickhouse_tool.query.builder import (
    CURSOR_COLUMN,
    FOLLOW_BATCH_LIMIT,
    METRIC_CURSOR_COLUMN,
    build_container_preflight,
    build_logs_since,
    build_logs_since_arrival,
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
            blocks = _stream_blocks(client, statement)
            if row_transform is not None:
                blocks = map(row_transform, blocks)
            for line in formatter.format_stream(blocks):
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
        names = (
            column_names if column_names is not None else tuple(f"col{i}" for i in range(len(row)))
        )
        columns = tuple(ColumnMeta(name=name, ch_type="") for name in names)
        yield RowSet(columns=columns, rows=(row,), row_count=1)


def run_follow(
    client: ChClient,
    *,
    intent: LogsIntent,
    table: str,
    formatter: Formatter,
    since: str | tuple[str, str],
    poll_interval: float = 2.0,
    arrival: bool = False,
    has_inserted_at: bool | None = None,
    row_transform: Callable[[RowSet], RowSet] | None = None,
) -> None:
    """Poll for rows after ``since`` and print each batch as it arrives.

    ``arrival`` follows the ``(InsertedAt, Timestamp)`` cursor, else the
    event-time ``Timestamp`` cursor. Runs until interrupted.
    """
    cursor: tuple[str, ...] = (since,) if isinstance(since, str) else since

    def build(at: tuple[str, ...]) -> SqlStatement:
        if arrival:
            return build_logs_since_arrival(intent, table, (at[0], at[1]))
        return build_logs_since(intent, table, at[0], has_inserted_at)

    try:
        statement = build(cursor)
        if statement.meta.get("container_preflight_required"):
            _run_container_preflight(client, statement, table)
        while True:
            rows = client.execute(statement)
            if rows.row_count:
                cursor, visible = _split_cursor(rows)
                if row_transform is not None:
                    visible = row_transform(visible)
                _emit_batch(formatter.format(visible))
            _sleep_when_caught_up(rows, poll_interval)
            statement = build(cursor)
    finally:
        client.close()


def _split_cursor(rows: RowSet) -> tuple[tuple[str, ...], RowSet]:
    """Read every ``__cursor*`` column off the last row, then drop those columns."""
    idx = [i for i, col in enumerate(rows.columns) if col.name.startswith("__cursor")]
    # arrival cursor is (InsertedAt, Timestamp); the builders project them in that order
    cursor = tuple(str(rows.rows[-1][i]) for i in idx)
    keep = [i for i in range(len(rows.columns)) if i not in idx]
    visible = RowSet(
        columns=tuple(rows.columns[i] for i in keep),
        rows=tuple(tuple(row[i] for i in keep) for row in rows.rows),
        row_count=rows.row_count,
    )
    return cursor, visible


def _emit_batch(lines: Iterable[str]) -> None:
    """Print one poll's lines and flush, so a pipe reader sees them now."""
    for line in lines:
        print(line)
    sys.stdout.flush()


def _sleep_when_caught_up(rows: RowSet, poll_interval: float) -> None:
    """A full batch means more rows are waiting: poll again at once."""
    if rows.row_count < FOLLOW_BATCH_LIMIT:
        time.sleep(poll_interval)


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
                _emit_batch(formatter.format(visible))
            _sleep_when_caught_up(rows, poll_interval)
            statement = build_metric_values_since(query, table, cursor)
    finally:
        client.close()
