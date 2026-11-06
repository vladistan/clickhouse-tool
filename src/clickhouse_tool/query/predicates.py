"""One function per CLI filter flag, each returning a bound predicate.

Every fragment binds its user value as a parameter. No function here
joins clauses with OR, since that can defeat index usage. Predicates
only ever combine with AND.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.query.timerange import parse_time_range

_SEVERITY_LADDER: dict[str, int] = {
    "trace": 1,
    "debug": 5,
    "info": 9,
    "warn": 13,
    "error": 17,
    "fatal": 21,
}

_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9]{3,}$")


class Predicate(NamedTuple):
    """A WHERE-clause fragment paired with the values it binds."""

    sql: str
    params: dict[str, object]


def host_predicate(value: str, pname: str = "host") -> Predicate:
    return Predicate(sql=f"HostName = %({pname})s", params={pname: value})


def service_predicate(value: str, pname: str = "service") -> Predicate:
    return Predicate(sql=f"ServiceName = %({pname})s", params={pname: value})


def namespace_predicate(value: str, pname: str = "namespace") -> Predicate:
    return Predicate(sql=f"Namespace = %({pname})s", params={pname: value})


def container_predicate(value: str, pname: str = "container") -> Predicate:
    """Map-key predicate against LogAttributes. Callers must also request
    a preflight (see builder.build_container_preflight) before trusting a
    container-scoped result."""
    return Predicate(sql=f"LogAttributes['container_name'] = %({pname})s", params={pname: value})


def level_predicate(level: str, pname: str = "level") -> Predicate:
    if level not in _SEVERITY_LADDER:
        accepted = ", ".join(_SEVERITY_LADDER)
        raise ConfigError(f"unknown level '{level}'; accepted: {accepted}")
    return Predicate(sql=f"SeverityNumber >= %({pname})s", params={pname: _SEVERITY_LADDER[level]})


def metric_name_predicate(name: str, pname: str = "name") -> Predicate:
    """Matches an exact metric name or, for a stem like ``k8s.node.memory``, every child."""
    return Predicate(sql=f"startsWith(MetricName, %({pname})s)", params={pname: name})


def since_predicate(cursor: object, pname: str = "since", column: str = "Timestamp") -> Predicate:
    """Row-append predicate for polling: rows strictly after ``cursor``."""
    return Predicate(sql=f"{column} > %({pname})s", params={pname: cursor})


def time_predicate(
    window: str, pname: str = "tr", column: str = "Timestamp", upper_bound: bool = True
) -> Predicate:
    """Timestamp window plus its toDate partition-pruning companion.

    ``upper_bound`` caps the window at ``now()``; a source with a bad
    clock otherwise fills every newest-first view with future rows.
    """
    count, unit = parse_time_range(window)
    count_param = f"{pname}_count"
    sql = (
        f"{column} >= now() - INTERVAL %({count_param})s {unit} "
        f"AND toDate({column}) >= toDate(now() - INTERVAL %({count_param})s {unit})"
    )
    if upper_bound:
        sql += f" AND {column} <= now()"
    return Predicate(sql=sql, params={count_param: count})


def build_search_predicate(term: str, pname: str = "search") -> tuple[Predicate, str]:
    """Token-index match for a single plain word, substring match otherwise.

    Quote, percent, underscore and backslash characters in `term` are bound
    as part of the parameter value, never escaped into the SQL text.
    """
    if _TOKEN_PATTERN.fullmatch(term):
        return Predicate(sql=f"hasToken(Body, %({pname})s)", params={pname: term}), "token"
    return Predicate(sql=f"Body ILIKE %({pname})s", params={pname: f"%{term}%"}), "ilike"
