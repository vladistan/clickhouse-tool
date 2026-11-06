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
from clickhouse_tool.core.monitoring import report_crash, setup_sentry

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


def _command_names(typer_app: typer.Typer) -> frozenset[str]:
    """Every command and sub-app name registered on ``typer_app``, recursively."""
    names = {command.name for command in typer_app.registered_commands if command.name}
    for group in typer_app.registered_groups:
        if group.name:
            names.add(group.name)
        if group.typer_instance is not None:
            names |= _command_names(group.typer_instance)
    return frozenset(names)


_COMMAND_NAMES = _command_names(app)
# Set to any non-empty value to raise after startup: verifies crash reporting end to end.
FORCE_CRASH_ENV_VAR = "CLICKHOUSE_TOOL_FORCE_CRASH"


def run() -> None:
    """Entry point installed as the ``clickhouse-tool`` console script."""
    setup_sentry(commands=_COMMAND_NAMES)
    try:
        if os.environ.get(FORCE_CRASH_ENV_VAR):
            raise RuntimeError(f"forced crash: {FORCE_CRASH_ENV_VAR} is set")
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
    except Exception as exc:
        report_crash(exc)
        typer.echo(f"Error: {exc}", err=True)
        raise SystemExit(int(ExitCode.GENERAL_ERROR)) from None


def _silence_broken_pipe() -> None:
    """Redirect stdout to devnull so Python's shutdown doesn't report the pipe error."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.close(devnull)


if __name__ == "__main__":
    run()
