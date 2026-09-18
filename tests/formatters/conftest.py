"""Fixtures local to the formatters test subtree."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from clickhouse_tool.core.models import ColumnMeta, RowSet


def _build_rowset(columns: list[str], rows: list[tuple[object, ...]]) -> RowSet:
    return RowSet(
        columns=tuple(ColumnMeta(name=c, ch_type="String") for c in columns),
        rows=tuple(rows),
        row_count=len(rows),
        truncated=False,
    )


@pytest.fixture
def make_rowset() -> Callable[[list[str], list[tuple[object, ...]]], RowSet]:
    return _build_rowset


@pytest.fixture
def empty_rowset() -> RowSet:
    return RowSet(columns=(), rows=(), row_count=0, truncated=False)
