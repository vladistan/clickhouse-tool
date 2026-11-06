"""Shared fixtures. Frozen for the duration of Wave 1 -- a Wave 1 track adds
its own fixtures to its own subtree's conftest.py, never here."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from clickhouse_tool.core.models import ColumnMeta, RowSet, SqlStatement


class FakeChClient:
    """A minimal in-memory ChClient double.

    Construct with a mapping of exact SQL text to the RowSet it should
    return, or pass ``raises`` to make every call raise that exception.
    """

    def __init__(
        self,
        responses: dict[str, RowSet] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._responses = responses or {}
        self._raises = raises
        self.closed = False
        self.executed: list[SqlStatement] = []

    def ping(self) -> None:
        if self._raises is not None:
            raise self._raises

    def execute(self, statement: SqlStatement) -> RowSet:
        self.executed.append(statement)
        if self._raises is not None:
            raise self._raises
        return self._responses.get(statement.sql, empty_rowset())

    def stream(self, statement: SqlStatement) -> Iterator[tuple[object, ...]]:
        self.executed.append(statement)
        if self._raises is not None:
            raise self._raises
        rowset = self._responses.get(statement.sql, empty_rowset())
        yield from rowset.rows

    def close(self) -> None:
        self.closed = True


def empty_rowset() -> RowSet:
    return RowSet(columns=(), rows=(), row_count=0, truncated=False)


def make_rowset(columns: list[str], rows: list[tuple[object, ...]]) -> RowSet:
    return RowSet(
        columns=tuple(ColumnMeta(name=c, ch_type="String") for c in columns),
        rows=tuple(rows),
        row_count=len(rows),
        truncated=False,
    )


@pytest.fixture
def fake_client() -> FakeChClient:
    return FakeChClient()


@pytest.fixture(autouse=True)
def _sentry_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite from reporting to the real Sentry project.

    ``run()`` reports unexpected crashes; tests that provoke one would
    otherwise send it to the built-in DSN.
    """
    monkeypatch.setenv("CLICKHOUSE_TOOL_SENTRY_DSN", "")
