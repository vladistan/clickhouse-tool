"""Protocol between SQL construction and the network.

Implementations accept :class:`~clickhouse_tool.core.models.SqlStatement`
without inspecting or rewriting text. Text arrives already parameterized
from the query builder.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from clickhouse_tool.core.models import RowSet, SqlStatement


@runtime_checkable
class ChClient(Protocol):
    """A connection to one ClickHouse server, over one transport."""

    def ping(self) -> None:
        """Verify the connection is live. Raises a typed error if not."""
        ...

    def execute(self, statement: SqlStatement) -> RowSet:
        """Execute ``statement`` and return the full result, buffered."""
        ...

    def stream(self, statement: SqlStatement) -> Iterator[tuple[object, ...]]:
        """Execute ``statement`` and yield rows one at a time."""
        ...

    def close(self) -> None:
        """Release the underlying connection."""
        ...
