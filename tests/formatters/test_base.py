"""Tests for Formatter protocol and FormatterRegistry."""

from collections.abc import Iterator
from typing import ClassVar

import pytest

from clickhouse_tool.core.models import RowSet
from clickhouse_tool.formatters.base import Formatter, FormatterRegistry

pytestmark = pytest.mark.unit


class _BufferingFormatter:
    streaming: ClassVar[bool] = False

    def format(self, rows: RowSet) -> Iterator[str]:
        yield "buffered"

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        for _block in blocks:
            yield "buffered-block"


class _StreamingFormatter:
    streaming: ClassVar[bool] = True

    def format(self, rows: RowSet) -> Iterator[str]:
        yield "streamed"

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        for _block in blocks:
            yield "streamed-block"


def test_formatter_protocol_accepts_conforming_class() -> None:
    assert isinstance(_BufferingFormatter(), Formatter)
    assert isinstance(_StreamingFormatter(), Formatter)


def test_streaming_flag_distinguishable_without_instantiating() -> None:
    assert _BufferingFormatter.streaming is False
    assert _StreamingFormatter.streaming is True


def test_registry_returns_registered_formatter_by_name() -> None:
    registry = FormatterRegistry()
    registry.register("buffered", _BufferingFormatter)
    assert registry.get("buffered") is _BufferingFormatter


def test_registry_raises_clear_error_for_unknown_name() -> None:
    registry = FormatterRegistry()
    registry.register("buffered", _BufferingFormatter)
    with pytest.raises(KeyError, match="unknown formatter 'nope'"):
        registry.get("nope")


def test_registry_names_lists_all_registered() -> None:
    registry = FormatterRegistry()
    registry.register("b", _BufferingFormatter)
    registry.register("a", _StreamingFormatter)
    assert registry.names() == ("a", "b")


def test_exactly_one_registry_instance_in_package() -> None:
    from clickhouse_tool.formatters.base import registry

    assert isinstance(registry, FormatterRegistry)
