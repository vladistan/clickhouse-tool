"""The tables verb: enumerate what `list`/`lift`/`query` may safely target."""

from __future__ import annotations

import typer

from clickhouse_tool.cli import wiring
from clickhouse_tool.cli.runner import run_statement
from clickhouse_tool.core.logging import setup_logging
from clickhouse_tool.formatters import get_formatter
from clickhouse_tool.query.builder import build_tables_list


def tables(
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """List every table the allow-list permits `list`/`lift`/`query` to target."""
    setup_logging(verbose)
    resolved = wiring.load_profile(profile)
    statement = build_tables_list(resolved.database)
    formatter = get_formatter(output_format or resolved.default_format)
    client = wiring.open_client(resolved)
    run_statement(client, statement, formatter)
