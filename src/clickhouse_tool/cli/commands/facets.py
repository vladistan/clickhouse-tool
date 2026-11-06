"""The host and service verbs: a grouped count over the shared time and filter flags."""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from clickhouse_tool.cli import wiring
from clickhouse_tool.cli.runner import run_statement
from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.humanize import format_relative_time
from clickhouse_tool.core.logging import setup_logging
from clickhouse_tool.core.models import RowSet
from clickhouse_tool.formatters import get_formatter
from clickhouse_tool.query.builder import build_facet, build_metrics_facet
from clickhouse_tool.query.intents import FacetIntent, Filters

_SUPPORTED_STREAMS = ("logs", "metrics")


def _humanize_last_seen(rows: RowSet) -> RowSet:
    """Replace the raw `last_seen` datetime with a rendered '2h 20m ago' string."""
    idx = next(i for i, col in enumerate(rows.columns) if col.name == "last_seen")
    now = datetime.now(UTC)
    new_rows = tuple(
        (*row[:idx], format_relative_time(row[idx], now=now), *row[idx + 1 :]) for row in rows.rows
    )
    return RowSet(
        columns=rows.columns, rows=new_rows, row_count=rows.row_count, truncated=rows.truncated
    )


def _facet(
    facet_field: str,
    *,
    profile: str | None,
    namespace: str | None,
    container: str | None,
    level: str | None,
    time_range: str | None,
    search: str | None,
    stream: str,
    limit: int,
    unbounded: bool,
    output_format: str | None,
    verbose: bool,
) -> None:
    setup_logging(verbose)
    if stream not in _SUPPORTED_STREAMS:
        accepted = ", ".join(_SUPPORTED_STREAMS)
        raise ConfigError(f"unsupported stream '{stream}'; accepted: {accepted}")
    resolved = wiring.load_profile(profile)
    filters = Filters(
        namespace=namespace,
        container=container,
        level=level,
        time_range=time_range if time_range is not None else resolved.default_window,
        search=search,
    )
    intent = FacetIntent(facet_field=facet_field, filters=filters, limit=limit, unbounded=unbounded)
    if stream == "metrics":
        table = wiring.resolve_metrics_table(resolved)
        statement = build_metrics_facet(intent, table)
    else:
        table = wiring.resolve_logs_table(resolved)
        statement = build_facet(intent, table)
    formatter = get_formatter(output_format or resolved.default_format)
    client = wiring.open_client(resolved)
    run_statement(client, statement, formatter, table=table, row_transform=_humanize_last_seen)


def hosts(
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    namespace: str | None = typer.Option(None, "--namespace", help="Filter by namespace"),
    container: str | None = typer.Option(None, "--container", help="Filter by container name"),
    level: str | None = typer.Option(None, "--level", "-l", help="Minimum severity level"),
    time_range: str | None = typer.Option(
        None, "-t", "--time-range", help="Time window, e.g. 15m, 2h, 1d [default: 2h]"
    ),
    search: str | None = typer.Option(None, "--search", "-s", help="Full-text search term"),
    stream: str = typer.Option("metrics", "--stream", help="Data stream to facet over"),
    limit: int = typer.Option(200, "-n", "--limit", help="Maximum number of hosts returned"),
    unbounded: bool = typer.Option(False, "--unbounded", help="Return every host, no cap"),
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Count activity grouped by host, metrics stream by default."""
    _facet(
        "host",
        profile=profile,
        namespace=namespace,
        container=container,
        level=level,
        time_range=time_range,
        search=search,
        stream=stream,
        limit=limit,
        unbounded=unbounded,
        output_format=output_format,
        verbose=verbose,
    )


def services(
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    namespace: str | None = typer.Option(None, "--namespace", help="Filter by namespace"),
    container: str | None = typer.Option(None, "--container", help="Filter by container name"),
    level: str | None = typer.Option(None, "--level", "-l", help="Minimum severity level"),
    time_range: str | None = typer.Option(
        None, "-t", "--time-range", help="Time window, e.g. 15m, 2h, 1d [default: 2h]"
    ),
    search: str | None = typer.Option(None, "--search", "-s", help="Full-text search term"),
    stream: str = typer.Option("metrics", "--stream", help="Data stream to facet over"),
    limit: int = typer.Option(200, "-n", "--limit", help="Maximum number of services returned"),
    unbounded: bool = typer.Option(False, "--unbounded", help="Return every service, no cap"),
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Count activity grouped by service, metrics stream by default."""
    _facet(
        "service",
        profile=profile,
        namespace=namespace,
        container=container,
        level=level,
        time_range=time_range,
        search=search,
        stream=stream,
        limit=limit,
        unbounded=unbounded,
        output_format=output_format,
        verbose=verbose,
    )
