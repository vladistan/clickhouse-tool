"""Rich-rendered table formatter.

Buffering. Rendering rules live here rather than in SQL so that display
formatting is a formatter concern, not a query concern.
"""

from __future__ import annotations

import io
import shutil
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import ClassVar

from rich.console import Console
from rich.table import Table
from rich.text import Text

from clickhouse_tool.core.humanize import humanize_number
from clickhouse_tool.core.logging import get_logger
from clickhouse_tool.core.models import RowSet

_MAX_CELL_LEN = 300
_TRUNCATION_MARKER = "... [truncated]"
_DEFAULT_WIDTH = 200
_MIN_COL_WIDTH = 6
_DEFAULT_DECIMALS = 2
_DEFAULT_TS_DECIMALS = 0
_DEFAULT_TS_PRECISION = "s"


def _render_timestamp(value: datetime, ts_decimals: int, ts_precision: str) -> str:
    if ts_precision == "m":
        return value.strftime("%Y-%m-%d %H:%M")
    base = value.strftime("%Y-%m-%d %H:%M:%S")
    if ts_decimals <= 0:
        return base
    fraction = f"{value.microsecond:06d}"[:ts_decimals]
    return f"{base}.{fraction}"


def _render_cell(
    value: object,
    decimals: int = _DEFAULT_DECIMALS,
    ts_decimals: int = _DEFAULT_TS_DECIMALS,
    ts_precision: str = _DEFAULT_TS_PRECISION,
) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        text = str(value)
    elif isinstance(value, (int, float)):
        text = humanize_number(value, decimals=decimals)
    elif isinstance(value, datetime):
        text = _render_timestamp(value, ts_decimals, ts_precision)
    else:
        text = str(value)
    if len(text) > _MAX_CELL_LEN:
        return text[: _MAX_CELL_LEN - len(_TRUNCATION_MARKER)] + _TRUNCATION_MARKER
    return text


def _measure_natural_widths(
    names: Sequence[str],
    rows: Sequence[tuple[object, ...]],
    decimals: int = _DEFAULT_DECIMALS,
    ts_decimals: int = _DEFAULT_TS_DECIMALS,
    ts_precision: str = _DEFAULT_TS_PRECISION,
) -> dict[str, int]:
    """Each column's own content-driven width: header length vs. its widest cell."""
    widths: dict[str, int] = {}
    for i, name in enumerate(names):
        cell_lens = (len(_render_cell(row[i], decimals, ts_decimals, ts_precision)) for row in rows)
        widths[name] = max(len(name), max(cell_lens, default=0), _MIN_COL_WIDTH)
    return widths


def _fixed_column_widths(
    names: Sequence[str],
    rows: Sequence[tuple[object, ...]],
    total_width: int,
    decimals: int = _DEFAULT_DECIMALS,
    ts_decimals: int = _DEFAULT_TS_DECIMALS,
    ts_precision: str = _DEFAULT_TS_PRECISION,
) -> dict[str, int]:
    """Measure natural per-column widths from one batch, fixed for every later render.

    Columns keep their own distinct widths. Only the single widest
    column gives up space when the row does not fit the terminal.
    """
    widths = _measure_natural_widths(names, rows, decimals, ts_decimals, ts_precision)
    overhead = len(names) * 3 + 1  # rich's own per-column border/padding budget
    available = max(total_width - overhead, len(names) * _MIN_COL_WIDTH)
    overflow = sum(widths.values()) - available
    if overflow > 0:
        widest = max(widths, key=lambda name: widths[name])
        widths[widest] = max(_MIN_COL_WIDTH, widths[widest] - overflow)
    return widths


class TableFormatter:
    """Renders a RowSet as a rich table. Not streaming.

    In ``follow`` mode, no header prints. Each column's width comes from
    the first batch, then stays fixed instead of re-fitting per poll.
    """

    streaming: ClassVar[bool] = False

    def __init__(
        self,
        *,
        follow: bool = False,
        decimals: int = _DEFAULT_DECIMALS,
        ts_decimals: int = _DEFAULT_TS_DECIMALS,
        ts_precision: str = _DEFAULT_TS_PRECISION,
    ) -> None:
        self._follow = follow
        self._decimals = decimals
        self._ts_decimals = ts_decimals
        self._ts_precision = ts_precision
        self._column_widths: dict[str, int] | None = None

    def format(self, rows: RowSet) -> Iterator[str]:
        if not rows.columns:
            get_logger(__name__).info("zero-column result", row_count=rows.row_count)
            return

        names = [column.name for column in rows.columns]
        if self._follow and self._column_widths is None:
            terminal_width = shutil.get_terminal_size(fallback=(_DEFAULT_WIDTH, 24)).columns
            self._column_widths = _fixed_column_widths(
                names,
                rows.rows,
                terminal_width,
                self._decimals,
                self._ts_decimals,
                self._ts_precision,
            )

        table = Table(show_header=not self._follow, show_edge=not self._follow)
        for name in names:
            width = self._column_widths.get(name) if self._column_widths else None
            table.add_column(Text(name), width=width, overflow="ellipsis" if width else "fold")
        for row in rows.rows:
            # Text, not str: rich parses a bare str as markup, so a log line
            # holding "[/x]" raises and one holding "[red]" loses text.
            table.add_row(
                *(
                    Text(_render_cell(value, self._decimals, self._ts_decimals, self._ts_precision))
                    for value in row
                )
            )

        console_width = (
            shutil.get_terminal_size(fallback=(_DEFAULT_WIDTH, 24)).columns
            if self._follow
            else _DEFAULT_WIDTH
        )
        buffer = io.StringIO()
        console = Console(file=buffer, width=console_width)
        console.print(table)
        yield from buffer.getvalue().splitlines()

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        for block in blocks:
            yield from self.format(block)
