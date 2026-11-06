"""Shared result and statement vocabulary used by every module.

The query builder, backend clients, and every formatter speak only
these four types. No module may import a driver, a formatter, or CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ColumnMeta:
    """One column's name and its ClickHouse type, as returned by the server."""

    name: str
    ch_type: str


@dataclass(frozen=True, slots=True)
class RowSet:
    """A buffered query result.

    ``row_count`` and ``truncated`` are always present, even for
    empty or zero-column results. Callers can read them without
    checking for None.
    """

    columns: tuple[ColumnMeta, ...]
    rows: tuple[tuple[Any, ...], ...]
    row_count: int
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class SqlStatement:
    """Parameterized statement ready for backend execution.

    ``sql`` and ``params`` form the executable pair. ``settings`` are
    per-query ClickHouse settings. ``meta`` carries search hints for
    ``--verbose`` reporting and never affects equality.
    """

    sql: str
    params: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict, compare=False)
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QueryStats:
    """Server-reported execution stats, surfaced under ``--verbose``."""

    elapsed: float
    rows_read: int
    bytes_read: int
