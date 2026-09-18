"""Sort alias canonicalisation.

ORDER BY cannot bind as a parameter, so an unrecognised sort must never
reach SQL. Every token gets checked; an unrecognised one raises. No
raw-text fallback: a trailing clause gets rejected, not passed on.
"""

from __future__ import annotations

from clickhouse_tool.core.errors import ConfigError

SORT_ALIASES: dict[str, str] = {
    "@timestamp:desc": "Timestamp DESC",
    "@timestamp:asc": "Timestamp ASC",
    "severity_number:desc": "SeverityNumber DESC",
    "severity_number:asc": "SeverityNumber ASC",
    "ts:desc": "Timestamp DESC",
    "ts:asc": "Timestamp ASC",
}

_NATIVE_COLUMNS = frozenset({"Timestamp", "SeverityNumber", "HostName", "ServiceName"})
_DIRECTIONS = frozenset({"ASC", "DESC"})

DEFAULT_SORT = "Timestamp DESC"


def canonicalise_sort(sort: str | None) -> str:
    """Resolve an ES-style alias or a native column name to an ORDER BY clause.

    Raises :class:`ConfigError` for anything matching neither the alias
    map nor `<native column>[ <ASC|DESC>]` exactly -- no fallback returns
    unvalidated text.
    """
    if sort is None:
        return DEFAULT_SORT
    if sort in SORT_ALIASES:
        return SORT_ALIASES[sort]
    tokens = sort.split()
    if len(tokens) in (1, 2) and tokens[0] in _NATIVE_COLUMNS and (
        len(tokens) == 1 or tokens[1] in _DIRECTIONS
    ):
        return sort
    accepted = ", ".join(sorted(set(SORT_ALIASES) | _NATIVE_COLUMNS))
    raise ConfigError(f"unknown sort '{sort}'; accepted: {accepted}")
