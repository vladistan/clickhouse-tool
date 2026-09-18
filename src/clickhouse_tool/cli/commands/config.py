"""The skip-secrets verb: shows the resolved profile with provenance.

Never materialises secrets and never opens a connection, so it works
with no AWS credentials present at all.
"""

from __future__ import annotations

import json

import typer

from clickhouse_tool.cli import wiring


def config(
    profile: str | None = typer.Option(None, "--profile", help="Named connection profile"),
) -> None:
    """Show the resolved configuration, with secrets redacted."""
    resolved = wiring.load_profile(profile)
    print(json.dumps(resolved.model_dump(), indent=2, default=str))
