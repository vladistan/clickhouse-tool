"""The baseline verb for querying raw log rows. The only verb that may stream."""

from __future__ import annotations

import shutil
import sys

import typer

from clickhouse_tool.cli import wiring
from clickhouse_tool.cli.runner import run_follow, run_statement
from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.logging import setup_logging
from clickhouse_tool.core.models import RowSet
from clickhouse_tool.core.schema import INSERTED_AT, NAMESPACE, probe_columns
from clickhouse_tool.core.timezone import resolve_display_timezone
from clickhouse_tool.formatters import Formatter, get_formatter
from clickhouse_tool.formatters.logline import LayoutOptions, LogLineFormatter
from clickhouse_tool.query.builder import (
    build_arrival_start_cursor,
    build_count,
    build_initial_cursor,
    build_latest_cursor,
    build_logs,
)
from clickhouse_tool.query.columns import apply_lag_column, layout_hidden_columns
from clickhouse_tool.query.intents import CountIntent, Filters, LogsIntent


def logs(
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    host: str | None = typer.Option(None, "--host", "-h", help="Filter by host name"),
    service: str | None = typer.Option(None, "--service", help="Filter by service name"),
    namespace: str | None = typer.Option(None, "--namespace", help="Filter by namespace"),
    container: str | None = typer.Option(None, "--container", help="Filter by container name"),
    level: str | None = typer.Option(None, "--level", "-l", help="Minimum severity level"),
    time_range: str | None = typer.Option(
        None, "-t", "--time-range", help="Time window, e.g. 15m, 2h, 1d [default: 2h]"
    ),
    search: str | None = typer.Option(None, "--search", "-s", help="Full-text search term"),
    sort: str | None = typer.Option(None, "--sort", help="Sort order, e.g. @timestamp:desc"),
    full: bool = typer.Option(False, "--full", help="Select every column, nested output"),
    raw: bool = typer.Option(False, "--raw", help="Alias for --full"),
    count: bool = typer.Option(False, "--count", help="Return a row count instead of rows"),
    follow: bool = typer.Option(
        False, "--follow", help="Poll continuously for new rows as they arrive (Ctrl-C to stop)"
    ),
    by_event_time: bool = typer.Option(
        False, "--by-event-time", help="With --follow: order by event time instead of arrival"
    ),
    utc: bool = typer.Option(False, "--utc", help="Show timestamps in UTC instead of local time"),
    interval: float = typer.Option(2.0, "--interval", help="Seconds between --follow polls"),
    wrap: bool = typer.Option(False, "--wrap", help="Table on a terminal: wrap long messages"),
    no_glyphs: bool = typer.Option(
        False, "--no-glyphs", help="Table on a terminal: words, not glyphs"
    ),
    full_timestamps: bool = typer.Option(
        False, "--full-timestamps", help="Table on a terminal: always show the date"
    ),
    include_future: bool = typer.Option(
        False, "--include-future", help="Also show rows stamped later than now()"
    ),
    limit: int | None = typer.Option(None, "-n", "--limit", help="Maximum rows returned"),
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Query raw log rows."""
    setup_logging(verbose)
    if follow and count:
        raise ConfigError("--follow does not support --count")
    if follow and sort is not None:
        raise ConfigError("--follow always orders oldest-first and does not support --sort")
    if interval <= 0:
        raise ConfigError("--interval must be a positive number of seconds")
    resolved = wiring.load_profile(profile)
    table = wiring.resolve_logs_table(resolved)
    window = time_range if time_range is not None else resolved.default_window
    filters = Filters(
        host=host,
        service=service,
        namespace=namespace,
        container=container,
        level=level,
        time_range=window,
        search=search,
        include_future=include_future,
    )
    tz = resolve_display_timezone(utc=utc, configured=resolved.default_timezone)
    format_name = output_format or resolved.default_format
    line_layout = format_name == "table" and not (full or raw or count)
    client = wiring.open_client(resolved)
    table_columns = probe_columns(client, table)
    has_inserted_at = INSERTED_AT in table_columns
    hidden = layout_hidden_columns(NAMESPACE in table_columns) if line_layout else ()
    intent = LogsIntent(
        filters=filters, full=full, raw=raw, sort=sort, limit=limit, tz=tz, hidden=hidden
    )
    formatter: Formatter
    if line_layout:
        terminal = sys.stdout.isatty()
        formatter = LogLineFormatter(
            LayoutOptions(
                terminal=terminal,
                follow=follow,
                tz=tz,
                widths=resolved.layout.widths,
                terminal_width=shutil.get_terminal_size(fallback=(200, 24)).columns,
                glyphs=not no_glyphs,
                wrap=wrap,
                full_timestamps=full_timestamps,
            )
        )
    else:
        formatter = get_formatter(format_name, follow=follow)

    def flag_lag(rows: RowSet) -> RowSet:
        return apply_lag_column(rows, resolved.late_after_s, resolved.future_after_s)

    if follow:
        arrival = has_inserted_at and not by_event_time
        if arrival:
            start = client.execute(build_arrival_start_cursor()).rows[0]
            since: str | tuple[str, str] = (str(start[0]), str(start[1]))
        else:
            if not by_event_time:
                typer.echo(
                    f"note: {table} has no {INSERTED_AT} column; following by event time, "
                    "late rows may be skipped",
                    err=True,
                )
            latest = client.execute(build_latest_cursor(intent, table))
            since = (
                str(latest.rows[0][0])
                if latest.rows
                else str(client.execute(build_initial_cursor(window)).rows[0][0])
            )
        run_follow(
            client,
            intent=intent,
            table=table,
            formatter=formatter,
            since=since,
            poll_interval=interval,
            arrival=arrival,
            has_inserted_at=has_inserted_at,
            row_transform=flag_lag,
        )
        return
    if count:
        run_statement(
            client, build_count(CountIntent.from_logs_intent(intent), table), formatter, table=table
        )
        return
    statement = build_logs(intent, table, has_inserted_at)
    run_statement(client, statement, formatter, table=table, row_transform=flag_lag)
