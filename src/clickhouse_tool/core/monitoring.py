"""Sentry integration for error tracking and performance monitoring.

DSN defaults to the project's real Sentry endpoint; set
CLICKHOUSE_TOOL_SENTRY_DSN to override (e.g. point at a different
project, or set it empty to disable reporting).
"""

from __future__ import annotations

import os

import sentry_sdk

from clickhouse_tool.__about__ import __version__

_DSN_ENV_VAR = "CLICKHOUSE_TOOL_SENTRY_DSN"
_DEFAULT_DSN = "https://2931aea481d7dee6cfec6081784dd77c@o4508594232426496.ingest.us.sentry.io/4512104538832896"  # pragma: allowlist secret  # gitleaks:allow


def setup_sentry(environment: str = "local") -> None:
    """Initialize Sentry from the configured DSN, or no-op if explicitly disabled."""
    dsn = os.environ.get(_DSN_ENV_VAR, _DEFAULT_DSN)
    if not dsn:
        return
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=1.0,
        environment=environment,
        release=__version__,
        attach_stacktrace=True,
        send_default_pii=False,
    )
