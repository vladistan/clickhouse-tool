"""Logging configuration using structlog.

Logs go to stderr, to keep stdout clean for piped data output.
structlog defaults to stdout, a real hazard here --
``tests/test_logging.py`` asserts nothing reaches stdout.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

_LOG_LEVELS: dict[str, int] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


class _LazyStderrFactory:
    """Resolve ``sys.stderr`` at first log call, not at configure time.

    ``PrintLoggerFactory`` captures the handle once and breaks under a
    test runner that swaps ``sys.stderr`` between invocations.
    """

    def __call__(self, *args: Any, **kwargs: Any) -> structlog.PrintLogger:
        return structlog.PrintLogger(file=sys.stderr)


def setup_logging(verbose: bool = False) -> None:
    """Configure structlog for clickhouse-tool.

    Args:
        verbose: If True, set log level to DEBUG. Otherwise INFO.
    """
    log_level = "debug" if verbose else "info"

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_LOG_LEVELS[log_level]),
        context_class=dict,
        logger_factory=_LazyStderrFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> Any:
    """Get a structlog logger, optionally bound with a name.

    Never call this at module level -- always inside a function or
    ``__init__`` after :func:`setup_logging` has run.
    """
    logger = structlog.get_logger()
    if name:
        logger = logger.bind(logger=name)
    return logger
