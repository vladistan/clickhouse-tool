"""One dense line per log row, for ``logs -f table``.

Fixed column widths, no header, no borders; glyphs on a terminal and
ASCII when piped. The rich table stays for ``--full`` / ``--raw`` and
for every other verb.
"""

from __future__ import annotations

import textwrap
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import ClassVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clickhouse_tool.core.config import LayoutWidths
from clickhouse_tool.core.models import RowSet
from clickhouse_tool.formatters.cells import (
    cut,
    dim,
    escape_message,
    host_cell,
    marker_cell,
    pad,
    service_cell,
    severity_cell,
    source_cell,
    time_cell,
    visible_len,
)
from clickhouse_tool.query.columns import LAG_FIELD

SEPARATOR = " │ "
SHORT_TIME, FULL_TIME = 8, 19
# Hidden layout columns the builder projects for this formatter.
SEVERITY_COLUMN = "__sev"
NAMESPACE_COLUMN = "__ns"
LOG_SOURCE_COLUMN = "__src"
CONTAINER_COLUMN = "__ctr"
# Below these terminal widths, columns are dropped right to left.
_DROP_SERVICE_BELOW, _DROP_SOURCE_BELOW, _DROP_HOST_BELOW = 100, 80, 60


@dataclass(frozen=True, slots=True)
class LayoutOptions:
    """Everything the line renderer needs besides the rows."""

    terminal: bool
    follow: bool
    tz: str
    widths: LayoutWidths = field(default_factory=LayoutWidths)
    terminal_width: int = 200
    glyphs: bool = True
    wrap: bool = False
    full_timestamps: bool = False


class LogLineFormatter:
    """Renders each row of the default ``logs`` projection as one line."""

    streaming: ClassVar[bool] = False

    def __init__(self, options: LayoutOptions) -> None:
        self._o = options

    def format(self, rows: RowSet) -> Iterator[str]:
        names = [column.name for column in rows.columns]
        if not names:
            return
        today = _today(self._o.tz)
        for row in rows.rows:
            values = dict(zip(names, row, strict=True))
            yield from self._render(values, today)

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        for block in blocks:
            yield from self.format(block)

    def _render(self, values: dict[str, object], today: date) -> Iterator[str]:
        o = self._o
        short = o.follow and o.terminal and not o.full_timestamps
        cells = [
            pad(
                marker_cell(_int_or_none(values.get(LAG_FIELD)), terminal=o.terminal),
                2 if o.terminal else 1,
            ),
            pad(
                time_cell(str(values.get("ts", "")), today=today, short=short),
                SHORT_TIME if short else FULL_TIME,
            ),
            pad(
                severity_cell(
                    _int_or_none(values.get(SEVERITY_COLUMN)), terminal=o.terminal, glyphs=o.glyphs
                ),
                self._severity_width(),
            ),
        ]
        width = o.terminal_width if o.terminal else None
        if width is None or width >= _DROP_HOST_BELOW:
            cells.append(
                self._blank_or(host_cell(str(values.get("host", "")), o.widths.host), o.widths.host)
            )
        if width is None or width >= _DROP_SOURCE_BELOW:
            source = source_cell(
                str(values.get(NAMESPACE_COLUMN) or ""),
                str(values.get(LOG_SOURCE_COLUMN) or ""),
                str(values.get(CONTAINER_COLUMN) or ""),
                o.widths.source,
            )
            cells.append(self._blank_or(source, o.widths.source))
        if width is None or width >= _DROP_SERVICE_BELOW:
            service = service_cell(str(values.get("service", "")), o.widths.service)
            cells.append(self._blank_or(service, o.widths.service))
        prefix = " ".join(cells) + SEPARATOR
        message = escape_message(str(values.get("msg", "")), wrap=o.wrap and o.terminal)
        if width is None:
            yield prefix + message
            return
        room = max(width - visible_len(prefix), 8)
        if not o.wrap:
            yield prefix + cut(message, room)
            return
        indent = " " * visible_len(prefix)
        first = True
        for paragraph in message.split("\n"):
            for piece in textwrap.wrap(paragraph, room) or [""]:
                yield (prefix if first else indent) + piece
                first = False

    def _severity_width(self) -> int:
        if not self._o.terminal:
            return 1
        return 5 if not self._o.glyphs else 4

    def _blank_or(self, text: str, width: int) -> str:
        return pad(text or dim("-", self._o.terminal), width)


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(value)  # type: ignore[call-overload]


def _today(tz: str) -> date:
    try:
        return datetime.now(ZoneInfo(tz)).date()
    except (ZoneInfoNotFoundError, ValueError):
        return datetime.now().astimezone().date()
