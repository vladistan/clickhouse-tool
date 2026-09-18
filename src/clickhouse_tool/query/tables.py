"""Table allow-list for `list`/`lift`.

Table names cannot bind as a parameter. Literal membership is the
injection defense here, layered with the server's readonly=2.
"""

from __future__ import annotations

import re

from clickhouse_tool.core.errors import ConfigError

_OTEL_TABLE_PATTERN = re.compile(r"^otel\.[A-Za-z_][A-Za-z0-9_]*$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

SYSTEM_TABLES = frozenset(
    {
        "system.parts",
        "system.errors",
        "system.tables",
        "system.columns",
        "system.metrics",
        "system.asynchronous_metrics",
        "system.query_log",
    }
)


def validate_table(name: str) -> str:
    """Accept `otel.*` identifiers and the seven enumerated system tables."""
    if _OTEL_TABLE_PATTERN.match(name) or name in SYSTEM_TABLES:
        return name
    accepted = ", ".join(sorted(SYSTEM_TABLES))
    raise ConfigError(f"table '{name}' is not allow-listed; accepted: otel.* or one of: {accepted}")


def validate_qualified_table(database: str, table: str) -> str:
    """Validate a profile-derived database/table pair.

    Kept separate from the allow-list above: reusing it here rejects the
    shipped defaults, and widening it there opens what low-level verbs read.
    """
    for field_name, value in (("database", database), ("table", table)):
        if not _IDENTIFIER_PATTERN.match(value):
            raise ConfigError(f"invalid {field_name} identifier '{value}' in configured logs table")
    return f"{database}.{table}"
