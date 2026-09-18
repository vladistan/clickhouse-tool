"""The raw-SQL variant path; the query builder is not involved.

Read-only safety comes solely from the server-side ``readonly=2`` setting.
This module never parses the SQL. Server errors echo verbatim: the user
wrote the query.
"""

from __future__ import annotations

import sys

import typer

from clickhouse_tool.cli import wiring
from clickhouse_tool.cli.runner import run_statement
from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.logging import setup_logging
from clickhouse_tool.core.models import SqlStatement
from clickhouse_tool.formatters import get_formatter


def _resolve_sql(sql_argument: str | None) -> str:
    stdin_piped = not sys.stdin.isatty()
    if sql_argument is not None and stdin_piped:
        raise ConfigError("SQL given both as an argument and on stdin; supply exactly one")
    if sql_argument is not None:
        return sql_argument
    if not stdin_piped:
        raise ConfigError("no SQL given: pass it as an argument or pipe it on stdin")
    piped = sys.stdin.read()
    if not piped.strip():
        raise ConfigError("no SQL given: stdin was empty")
    return piped


def _parse_params(raw_params: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for raw in raw_params:
        name, sep, value = raw.partition("=")
        if not sep:
            raise ConfigError(f"malformed --param '{raw}'; expected name=value")
        params[name] = value
    return params


def query(
    sql: str | None = typer.Argument(None, help="SQL text (or pipe it on stdin)"),
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
    param: list[str] = typer.Option(
        [], "--param", help="Bind a named parameter, name=value, repeatable"
    ),
    output_format: str | None = typer.Option(None, "-f", "--format", help="Output format"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
) -> None:
    """Run a raw SQL statement, bypassing the query builder."""
    setup_logging(verbose)
    sql_text = _resolve_sql(sql)
    params = _parse_params(param)
    statement = SqlStatement(sql=sql_text, params=params)
    resolved = wiring.load_profile(profile)
    formatter = get_formatter(output_format or resolved.default_format)
    client = wiring.open_client(resolved)
    run_statement(client, statement, formatter)
