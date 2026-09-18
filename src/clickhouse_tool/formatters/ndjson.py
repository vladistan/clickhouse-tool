"""True row-by-row streaming NDJSON formatter.

The only streaming formatter. Written output stays written on a
mid-flight failure; the CLI reports it on stderr with a non-zero
exit, never suppressed here.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import ClassVar

from clickhouse_tool.core.models import RowSet
from clickhouse_tool.formatters.json import json_value


class NdjsonFormatter:
    """Renders each row as its own JSON line, as rows arrive. Streaming."""

    streaming: ClassVar[bool] = True

    def format(self, rows: RowSet) -> Iterator[str]:
        names = [column.name for column in rows.columns]
        for row in rows.rows:
            record = {name: json_value(value) for name, value in zip(names, row, strict=True)}
            yield json.dumps(record)

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        for block in blocks:
            yield from self.format(block)
