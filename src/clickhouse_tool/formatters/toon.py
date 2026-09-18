"""Hand-rolled TOON encoder, matching the invoice-tool dialect.

Name-count-fields header, two-space-indented rows, one-way emission.
A comma, quote, backslash, newline, CR, tab, edge whitespace, or
empty value gets quoted. ``None`` is ``-``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import ClassVar

from clickhouse_tool.core.models import RowSet

_RESULT_NAME = "result"
_NEEDS_QUOTE_CHARS = frozenset(',"\\\n\r\t')
_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\n": "\\n",
    "\r": "\\r",
    "\t": "\\t",
}


def _needs_quote(text: str) -> bool:
    if not text:
        return True
    if text != text.strip():
        return True
    return any(char in _NEEDS_QUOTE_CHARS for char in text)


def _escape(text: str) -> str:
    return "".join(_ESCAPES.get(char, char) for char in text)


def render_field(value: object) -> str:
    """Render one cell to its TOON text, quoting and escaping when required."""
    if value is None:
        return "-"
    text = value.isoformat(sep=" ") if isinstance(value, datetime) else str(value)
    if _needs_quote(text):
        return f'"{_escape(text)}"'
    return text


def encode(rows: RowSet) -> str:
    """Encode one RowSet as a TOON document: header line plus indented rows."""
    field_names = ",".join(column.name for column in rows.columns)
    header = f"{_RESULT_NAME}[{len(rows.rows)}]{{{field_names}}}:"
    lines = [header]
    for row in rows.rows:
        lines.append("  " + ",".join(render_field(value) for value in row))
    return "\n".join(lines) + "\n"


class ToonFormatter:
    """Renders a RowSet as a TOON document. Buffers -- needs the row count
    for its header before it can emit anything."""

    streaming: ClassVar[bool] = False

    def format(self, rows: RowSet) -> Iterator[str]:
        yield encode(rows)

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        for block in blocks:
            yield from self.format(block)
