"""One probe of a table's column names, run once per command.

Builders and formatters branch on what the table has (``InsertedAt``,
``Namespace``); table layouts differ between deployments.
"""

from __future__ import annotations

from clickhouse_tool.core.client.base import ChClient
from clickhouse_tool.core.models import SqlStatement

INSERTED_AT = "InsertedAt"
NAMESPACE = "Namespace"


def build_column_probe(table: str) -> SqlStatement:
    """``system.columns`` lookup for a validated ``database.table`` name."""
    database, _, name = table.partition(".")
    return SqlStatement(
        sql="SELECT name FROM system.columns WHERE database = %(db)s AND table = %(tbl)s",
        params={"db": database, "tbl": name},
    )


def probe_columns(client: ChClient, table: str) -> frozenset[str]:
    """The table's column names; empty when the table is unknown to the server."""
    result = client.execute(build_column_probe(table))
    return frozenset(str(row[0]) for row in result.rows)
