"""The typer application, its global options, and the sole error funnel.

The only place in the package that decides an exit code.
"""

from __future__ import annotations

import os
import sys

import typer

from clickhouse_tool.cli.commands import config as config_command
from clickhouse_tool.cli.commands import facets, listing, logs, metrics, query, tables
from clickhouse_tool.core.errors import ClickhouseToolError
from clickhouse_tool.core.exit_codes import ExitCode
from clickhouse_tool.core.monitoring import setup_sentry

# Frees the single-letter flag from typer's default help binding so a verb
# can use it for --host instead.
app = typer.Typer(
    help="clickhouse-tool -- query and administer the OTel ClickHouse pilot.",
    context_settings={"help_option_names": ["--help"]},
    no_args_is_help=True,
)

app.command("logs")(logs.logs)
app.command("hosts")(facets.hosts)
app.command("services")(facets.services)
app.command("list")(listing.list_)
app.command("lift")(listing.lift)
app.command("query")(query.query)
app.command("config")(config_command.config)
app.command("tables")(tables.tables)
app.add_typer(metrics.app, name="metrics")


def run() -> None:
    """Entry point installed as the ``clickhouse-tool`` console script."""
    setup_sentry()
    try:
        app()
    except ClickhouseToolError as exc:
        typer.echo(f"Error: {exc.message}", err=True)
        raise SystemExit(int(exc.exit_code)) from None
    except BrokenPipeError:
        _silence_broken_pipe()
        raise SystemExit(0) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover -- last-resort funnel
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(int(ExitCode.GENERAL_ERROR)) from None


def _silence_broken_pipe() -> None:
    """Redirect stdout to devnull so Python's shutdown doesn't report the pipe error."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.close(devnull)


if __name__ == "__main__":
    run()
