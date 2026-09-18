"""Formatter registry population.

Importing this package is sufficient for every format name to resolve --
each renderer registers itself here at import time.
"""

from __future__ import annotations

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.formatters.base import Formatter, FormatterRegistry, registry
from clickhouse_tool.formatters.json import JsonFormatter
from clickhouse_tool.formatters.ndjson import NdjsonFormatter
from clickhouse_tool.formatters.table import TableFormatter
from clickhouse_tool.formatters.toon import ToonFormatter

registry.register("json", JsonFormatter)
registry.register("ndjson", NdjsonFormatter)
registry.register("table", TableFormatter)
registry.register("toon", ToonFormatter)


def get_formatter(
    name: str,
    *,
    follow: bool = False,
    decimals: int = 2,
    ts_decimals: int = 0,
    ts_precision: str = "s",
) -> Formatter:
    """Resolve a format name to an instantiated formatter.

    Raises :class:`ConfigError` for an unregistered name, listing them.
    ``follow``/``decimals``/``ts_decimals``/``ts_precision`` only affect
    :class:`TableFormatter`; others ignore them.
    """
    try:
        formatter_cls = registry.get(name)
    except KeyError as exc:
        raise ConfigError(str(exc)) from exc
    if formatter_cls is TableFormatter:
        return TableFormatter(
            follow=follow, decimals=decimals, ts_decimals=ts_decimals, ts_precision=ts_precision
        )
    return formatter_cls()


__all__ = ["Formatter", "FormatterRegistry", "get_formatter", "registry"]
