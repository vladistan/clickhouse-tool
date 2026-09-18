"""Buffered JSON formatter.

The format for nested output: ``lift``, ``--full`` and ``--raw`` default
to it. Body values are never truncated here.
"""

from __future__ import annotations

import json as _json
from collections.abc import Iterator
from datetime import datetime
from typing import ClassVar

from clickhouse_tool.core.models import RowSet


def json_value(value: object) -> object:
    """Coerce one cell to a JSON-serializable value, recursing into Map/list columns."""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


class JsonFormatter:
    """Renders a RowSet as a JSON array of row objects. Not streaming."""

    streaming: ClassVar[bool] = False

    def format(self, rows: RowSet) -> Iterator[str]:
        names = [column.name for column in rows.columns]
        records = [
            {name: json_value(value) for name, value in zip(names, row, strict=True)}
            for row in rows.rows
        ]
        yield _json.dumps(records)

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        for block in blocks:
            yield from self.format(block)
