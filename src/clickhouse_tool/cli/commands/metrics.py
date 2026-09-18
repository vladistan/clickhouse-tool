"""The `metrics` verb group: names, summary stats, raw values, and histograms."""

from __future__ import annotations

import typer

from clickhouse_tool.cli import wiring
from clickhouse_tool.cli.commands.facets import _facet
from clickhouse_tool.cli.runner import run_metric_follow, run_statement
from clickhouse_tool.core.logging import setup_logging
from clickhouse_tool.formatters import get_formatter
from clickhouse_tool.query.builder import (
    build_initial_cursor,
    build_latest_metric_cursor,
    build_metric_histogram,
    build_metric_status,
    build_metric_values,
)
from clickhouse_tool.query.intents import MetricQuery
from clickhouse_tool.query.timerange import default_bucket_size, default_time_precision

app = typer.Typer(help="Metric names, summary stats, raw values, and histograms.")


@app.callback(invoke_without_command=True)
def _default_to_names(ctx: typer.Context) -> None:
    """Bare `metrics` behaves as `metrics names` with every default."""
    if ctx.invoked_subcommand is None:
        _names_impl(profile=None, time_range=None, limit=200, unbounded=False, output_format=None, verbose=False)


_NAME_ARG = typer.Argument(..., help="Exact metric name, or a dotted stem matching every child")
_HOST_OPT = typer.Option(None, "--host", "-h", help="Filter by host name")
_SERVICE_OPT = typer.Option(None, "--service", help="Filter by service name")
_TIME_RANGE_OPT = typer.Option(None, "-t", "--time-range", help="Time window, e.g. 15m, 2h, 1d [default: 2h]")
_DECIMALS_OPT = typer.Option(2, "--decimals", help="Decimal places for humanized numbers in table output")
_TS_DECIMALS_OPT = typer.Option(
    None,
    "--ts-decimals",
    help="Fractional-second digits for timestamps in table output "
    "[default: auto -- seconds under 3h, minutes for longer windows]",
)
_SPLIT_BY_OPT = typer.Option(None, "--split-by", help="Break results out by host, service, or host,service")


def _parse_split_by(split_by: str | None) -> tuple[str, ...]:
    return tuple(field.strip() for field in split_by.split(",")) if split_by else ()


def _resolve_ts_display(ts_decimals: int | None, window: str) -> tuple[int, str]:
    """An explicit ``--ts-decimals`` always implies second-level display."""
    if ts_decimals is not None:
        return ts_decimals, "s"
    return 0, default_time_precision(window)


def _query(name: str, host: str | None, service: str | None, window: str) -> MetricQuery:
    return MetricQuery(name=name, host=host, service=service, time_range=window)


def _names_impl(
    *,
    profile: str | None,
    time_range: str | None,
    limit: int,
    unbounded: bool,
    output_format: str | None,
    verbose: bool,
) -> None:
    _facet(
        "metric",
        profile=profile,
        namespace=None,
        container=None,
        level=None,
        time_range=time_range,
        search=None,
        stream="metrics",
        limit=limit,
        unbounded=unbounded,
        output_format=output_format,
        verbose=verbose,
    )


@app.command("names")
def names(
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    time_range: str | None = _TIME_RANGE_OPT,
    limit: int = typer.Option(200, "-n", "--limit", help="Maximum number of metric names returned"),
    unbounded: bool = typer.Option(False, "--unbounded", help="Return every metric name, no cap"),
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """List available metric names, with datapoint counts and last-seen time."""
    _names_impl(
        profile=profile,
        time_range=time_range,
        limit=limit,
        unbounded=unbounded,
        output_format=output_format,
        verbose=verbose,
    )


@app.command("status")
def status(
    name: str = _NAME_ARG,
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    host: str | None = _HOST_OPT,
    service: str | None = _SERVICE_OPT,
    time_range: str | None = _TIME_RANGE_OPT,
    split_by: str | None = _SPLIT_BY_OPT,
    decimals: int = _DECIMALS_OPT,
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Min/max/avg/stddev for a metric (or every metric under a dotted stem)."""
    setup_logging(verbose)
    resolved = wiring.load_profile(profile)
    table = wiring.resolve_metrics_table(resolved)
    window = time_range if time_range is not None else resolved.default_window
    statement = build_metric_status(_query(name, host, service, window), table, _parse_split_by(split_by))
    formatter = get_formatter(output_format or resolved.default_format, decimals=decimals)
    client = wiring.open_client(resolved)
    run_statement(client, statement, formatter, table=table)


@app.command("values")
def values(
    name: str = _NAME_ARG,
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    host: str | None = _HOST_OPT,
    service: str | None = _SERVICE_OPT,
    time_range: str | None = _TIME_RANGE_OPT,
    follow: bool = typer.Option(
        False, "--follow", help="Poll continuously for new datapoints, oldest first (Ctrl-C to stop)"
    ),
    limit: int | None = typer.Option(None, "-n", "--limit", help="Maximum datapoints returned"),
    decimals: int = _DECIMALS_OPT,
    ts_decimals: int | None = _TS_DECIMALS_OPT,
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Raw datapoints for a metric (or every metric under a dotted stem)."""
    setup_logging(verbose)
    if follow and limit is not None:
        raise typer.BadParameter("--follow does not support --limit") from None
    resolved = wiring.load_profile(profile)
    table = wiring.resolve_metrics_table(resolved)
    window = time_range if time_range is not None else resolved.default_window
    query = _query(name, host, service, window)
    resolved_ts_decimals, ts_precision = _resolve_ts_display(ts_decimals, window)
    formatter = get_formatter(
        output_format or resolved.default_format,
        follow=follow,
        decimals=decimals,
        ts_decimals=resolved_ts_decimals,
        ts_precision=ts_precision,
    )
    client = wiring.open_client(resolved)
    if follow:
        latest = client.execute(build_latest_metric_cursor(query, table))
        since = latest.rows[0][0] if latest.rows else client.execute(build_initial_cursor(window)).rows[0][0]
        run_metric_follow(client, query=query, table=table, formatter=formatter, since=since)
        return
    statement = build_metric_values(query, table, limit=limit)
    run_statement(client, statement, formatter, table=table)


@app.command("histogram")
def histogram(
    name: str = _NAME_ARG,
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    host: str | None = _HOST_OPT,
    service: str | None = _SERVICE_OPT,
    time_range: str | None = _TIME_RANGE_OPT,
    bucket: str | None = typer.Option(
        None, "--bucket", help="Bucket width, e.g. 5m, 1h [default: sized to the time window]"
    ),
    split_by: str | None = _SPLIT_BY_OPT,
    decimals: int = _DECIMALS_OPT,
    ts_decimals: int | None = _TS_DECIMALS_OPT,
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Time-bucketed min/max/avg/count for a metric (or every metric under a dotted stem)."""
    setup_logging(verbose)
    resolved = wiring.load_profile(profile)
    table = wiring.resolve_metrics_table(resolved)
    window = time_range if time_range is not None else resolved.default_window
    bucket_size = bucket if bucket is not None else default_bucket_size(window)
    statement = build_metric_histogram(
        _query(name, host, service, window), table, bucket_size, _parse_split_by(split_by)
    )
    resolved_ts_decimals, ts_precision = _resolve_ts_display(ts_decimals, window)
    formatter = get_formatter(
        output_format or resolved.default_format,
        decimals=decimals,
        ts_decimals=resolved_ts_decimals,
        ts_precision=ts_precision,
    )
    client = wiring.open_client(resolved)
    run_statement(client, statement, formatter, table=table)
