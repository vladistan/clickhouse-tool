"""The baseline verb for querying raw log rows. The only verb that may stream."""

from __future__ import annotations

import typer

from clickhouse_tool.cli import wiring
from clickhouse_tool.cli.runner import run_follow, run_statement
from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.logging import setup_logging
from clickhouse_tool.core.timezone import resolve_display_timezone
from clickhouse_tool.formatters import get_formatter
from clickhouse_tool.query.builder import build_count, build_initial_cursor, build_latest_cursor, build_logs
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
        False, "--follow", help="Poll continuously for new rows, oldest first (Ctrl-C to stop)"
    ),
    utc: bool = typer.Option(False, "--utc", help="Show timestamps in UTC instead of local time"),
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
    )
    tz = resolve_display_timezone(utc=utc, configured=resolved.default_timezone)
    intent = LogsIntent(filters=filters, full=full, raw=raw, sort=sort, limit=limit, tz=tz)
    formatter = get_formatter(output_format or resolved.default_format, follow=follow)
    client = wiring.open_client(resolved)
    if follow:
        latest = client.execute(build_latest_cursor(intent, table))
        since = latest.rows[0][0] if latest.rows else client.execute(build_initial_cursor(window)).rows[0][0]
        run_follow(client, intent=intent, table=table, formatter=formatter, since=since)
        return
    statement = (
        build_count(CountIntent.from_logs_intent(intent), table)
        if count
        else build_logs(intent, table)
    )
    run_statement(client, statement, formatter, table=table)
