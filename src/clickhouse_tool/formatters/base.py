"""Formatter Protocol and registry.

Formatters render :class:`~clickhouse_tool.core.models.RowSet` to output.
Own copy of the protocol; no imports from other tools.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar, Protocol, runtime_checkable

from clickhouse_tool.core.models import RowSet


@runtime_checkable
class Formatter(Protocol):
    """Renders a RowSet, or a stream of RowSets, to output lines."""

    streaming: ClassVar[bool]

    def format(self, rows: RowSet) -> Iterator[str]:
        """Render one buffered RowSet to output lines."""
        ...

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        """Render a stream of RowSet blocks to output lines, row by row."""
        ...


class FormatterRegistry:
    """A plain name-to-class map of registered formatters.

    Exactly one instance exists in the package (:data:`registry` below).
    A second is a defect.
    """

    def __init__(self) -> None:
        self._formatters: dict[str, type[Formatter]] = {}

    def register(self, name: str, formatter_cls: type[Formatter]) -> None:
        self._formatters[name] = formatter_cls

    def get(self, name: str) -> type[Formatter]:
        try:
            return self._formatters[name]
        except KeyError:
            known = ", ".join(sorted(self._formatters)) or "(none registered)"
            raise KeyError(f"unknown formatter {name!r}; known formatters: {known}") from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._formatters))


registry = FormatterRegistry()
