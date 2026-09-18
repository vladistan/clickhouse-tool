"""Low-level table inspection over the existing allow-list: list and lift."""

from __future__ import annotations

import typer

from clickhouse_tool.cli import wiring
from clickhouse_tool.cli.runner import run_statement
from clickhouse_tool.core.logging import setup_logging
from clickhouse_tool.formatters import get_formatter
from clickhouse_tool.query.builder import build_lift, build_list
from clickhouse_tool.query.intents import LiftIntent, ListIntent

_LIFT_DEFAULT_FORMAT = "json"


def list_(
    table: str = typer.Argument(..., help="Allow-listed table, e.g. otel.logs or system.parts"),
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    limit: int | None = typer.Option(None, "-n", "--limit", help="Maximum rows returned"),
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """List rows from an allow-listed table."""
    setup_logging(verbose)
    resolved = wiring.load_profile(profile)
    statement = build_list(ListIntent(table=table, limit=limit))
    formatter = get_formatter(output_format or resolved.default_format)
    client = wiring.open_client(resolved)
    run_statement(client, statement, formatter)


def lift(
    table: str = typer.Argument(..., help="Allow-listed table, e.g. otel.logs or system.parts"),
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Describe column metadata for an allow-listed table."""
    setup_logging(verbose)
    resolved = wiring.load_profile(profile)
    statement = build_lift(LiftIntent(table=table))
    formatter = get_formatter(output_format or _LIFT_DEFAULT_FORMAT)
    client = wiring.open_client(resolved)
    run_statement(client, statement, formatter)
