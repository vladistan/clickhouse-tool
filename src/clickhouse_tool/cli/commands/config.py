"""The skip-secrets verb: shows the resolved profile with provenance.

Never materialises secrets and never opens a connection, so it works
with no AWS credentials present at all.
"""

from __future__ import annotations

import json

import typer

from clickhouse_tool.cli import wiring
from clickhouse_tool.core.monitoring import mask_dsn, resolve_dsn


def config(
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
) -> None:
    """Show the resolved configuration, with secrets redacted."""
    resolved = wiring.load_profile(profile)
    shown = resolved.model_dump()
    sources = shown.pop("sources")
    dsn, dsn_source = resolve_dsn()
    shown["sentry_dsn"] = mask_dsn(dsn)
    sources["sentry_dsn"] = dsn_source
    shown["sources"] = sources
    print(json.dumps(shown, indent=2, default=str))
