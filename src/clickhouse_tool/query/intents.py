"""Intent dataclasses describing what the user asked for.

Each intent carries filter values only, with no SQL knowledge. The query
builder (builder.py) is the only module that turns an intent into a
SqlStatement.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Filters:
    """Filter values shared by every intent that scopes a time window."""

    host: str | None = None
    service: str | None = None
    namespace: str | None = None
    container: str | None = None
    level: str | None = None
    time_range: str | None = None
    search: str | None = None


@dataclass(frozen=True, slots=True)
class LogsIntent:
    """A request for raw log rows, as issued by the `logs` command."""

    filters: Filters = field(default_factory=Filters)
    columns: tuple[str, ...] | None = None
    full: bool = False
    raw: bool = False
    sort: str | None = None
    limit: int | None = None
    tz: str = "UTC"


@dataclass(frozen=True, slots=True)
class CountIntent:
    """A request for a row count, built from a LogsIntent's filters.

    A distinct type rather than a LogsIntent with a flag, so `--count`
    is a build-time variant instead of a string rewrite of rendered SQL.
    """

    filters: Filters = field(default_factory=Filters)

    @classmethod
    def from_logs_intent(cls, intent: LogsIntent) -> CountIntent:
        return cls(filters=intent.filters)


@dataclass(frozen=True, slots=True)
class FacetIntent:
    """A request for a grouped count over hosts or services."""

    facet_field: str
    filters: Filters = field(default_factory=Filters)
    limit: int = 200
    unbounded: bool = False


@dataclass(frozen=True, slots=True)
class MetricQuery:
    """A metric-name-scoped request: `metrics status`/`values`/`histogram`.

    ``name`` matches by exact string or, for a dotted stem, every child
    metric (see `query.predicates.metric_name_predicate`).
    """

    name: str
    host: str | None = None
    service: str | None = None
    time_range: str | None = None


@dataclass(frozen=True, slots=True)
class ListIntent:
    """A request to list rows from an allow-listed table, e.g. system.parts."""

    table: str
    columns: tuple[str, ...] | None = None
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class LiftIntent:
    """A request to describe column metadata for an allow-listed table."""

    table: str
