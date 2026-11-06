"""Sentry integration for error tracking and performance monitoring.

DSN precedence: CLICKHOUSE_TOOL_SENTRY_DSN, then ``sentry_dsn`` in the
TOML config, then the built-in endpoint. An empty override disables
reporting.
"""

from __future__ import annotations

import importlib.metadata
import json
import os
import sys
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

import sentry_sdk

from clickhouse_tool.__about__ import __version__
from clickhouse_tool.core.config import load_layers
from clickhouse_tool.core.errors import ConfigError

_DISTRIBUTION = "clickhouse-tool"
_DSN_ENV_VAR = "CLICKHOUSE_TOOL_SENTRY_DSN"
_FLUSH_TIMEOUT_S = 2.0
_DEFAULT_DSN = "https://2931aea481d7dee6cfec6081784dd77c@o4508594232426496.ingest.us.sentry.io/4512104538832896"  # pragma: allowlist secret  # gitleaks:allow


def resolve_dsn() -> tuple[str, str]:
    """Return the effective DSN and the name of the level that supplied it."""
    env_dsn = os.environ.get(_DSN_ENV_VAR)
    if env_dsn is not None:
        return env_dsn, f"env: {_DSN_ENV_VAR}"
    config_dsn = _config_file_dsn()
    if config_dsn is not None:
        return config_dsn, "config file"
    return _DEFAULT_DSN, "default"


def _config_file_dsn() -> str | None:
    # An unreadable config must not stop Sentry starting; the command
    # that needs the config reports the same error through the CLI funnel.
    try:
        return load_layers().sentry_dsn
    except (ConfigError, OSError):
        return None


def mask_dsn(dsn: str) -> str:
    """Render a DSN for display with its public key hidden."""
    if not dsn:
        return "(disabled)"
    key = urlsplit(dsn).username
    if not key:
        return dsn
    return dsn.replace(f"{key}@", "***@", 1)


def detect_environment() -> str:
    """``local`` for an editable or source-directory install, ``prod`` otherwise."""
    try:
        dist = importlib.metadata.distribution(_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError:
        return "local"
    return environment_for(dist.read_text("direct_url.json"))


def environment_for(direct_url_json: str | None) -> str:
    """Map a PEP 610 ``direct_url.json`` body to a Sentry environment name."""
    if direct_url_json is None:
        return "prod"
    return "local" if "dir_info" in json.loads(direct_url_json) else "prod"


def scrub_argv(argv: Iterable[str], commands: frozenset[str]) -> list[str]:
    """Keep command names and flag names; drop every value.

    Values can hold SQL text, search terms and host names.
    """
    kept: list[str] = []
    for token in argv:
        if token.startswith("--"):
            kept.append(token.split("=", 1)[0])
        elif token.startswith("-") and len(token) > 1:
            kept.append(token[:2])
        elif token in commands:
            kept.append(token)
    return kept


def setup_sentry(environment: str | None = None, commands: frozenset[str] = frozenset()) -> None:
    """Initialize Sentry from the resolved DSN, or no-op if explicitly disabled.

    ``commands`` names the CLI's subcommands, so reports can keep them
    while dropping argument values.
    """
    dsn, _source = resolve_dsn()
    if not dsn:
        return

    def before_send(event: Any, _hint: dict[str, Any]) -> Any:
        extra = event.get("extra")
        if extra and "sys.argv" in extra:
            extra["sys.argv"] = scrub_argv(sys.argv[1:], commands)
        return event

    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=1.0,
        environment=environment or detect_environment(),
        release=__version__,
        attach_stacktrace=True,
        send_default_pii=False,
        # Frame locals and breadcrumbs can hold credentials and SQL text.
        include_local_variables=False,
        max_breadcrumbs=0,
        before_send=before_send,
    )


def report_crash(exc: BaseException) -> None:
    """Send one unexpected exception and wait briefly for delivery."""
    sentry_sdk.capture_exception(exc)
    sentry_sdk.flush(timeout=_FLUSH_TIMEOUT_S)
