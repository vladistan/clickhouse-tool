"""Tests for the shared execute step: preflight decision, dispatch, cleanup."""

from __future__ import annotations

import os
import select
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from clickhouse_tool.cli import runner as runner_module
from clickhouse_tool.cli.runner import run_follow, run_statement
from clickhouse_tool.core.errors import UnsupportedFilterError
from clickhouse_tool.core.models import ColumnMeta, RowSet, SqlStatement
from clickhouse_tool.query.builder import (
    ARRIVAL_CURSOR_COLUMN,
    CURSOR_COLUMN,
    FOLLOW_BATCH_LIMIT,
    build_container_preflight,
)
from clickhouse_tool.query.intents import Filters, LogsIntent

pytestmark = pytest.mark.unit


def make_rowset(columns: list[str], rows: list[tuple[object, ...]]) -> RowSet:
    return RowSet(
        columns=tuple(ColumnMeta(name=c, ch_type="String") for c in columns),
        rows=tuple(rows),
        row_count=len(rows),
    )


def empty_rowset() -> RowSet:
    return RowSet(columns=(), rows=(), row_count=0)


class FakeChClient:
    """A minimal in-memory ChClient double, local to these tests."""

    def __init__(
        self, responses: dict[str, RowSet] | None = None, raises: Exception | None = None
    ) -> None:
        self._responses = responses or {}
        self._raises = raises
        self.closed = False

    def ping(self) -> None:  # pragma: no cover
        pass

    def execute(self, statement: SqlStatement) -> RowSet:
        if self._raises is not None:
            raise self._raises
        return self._responses.get(statement.sql, empty_rowset())

    def stream(self, statement: SqlStatement) -> Iterator[tuple[object, ...]]:
        if self._raises is not None:
            raise self._raises
        rowset = self._responses.get(statement.sql, empty_rowset())
        yield from rowset.rows

    def close(self) -> None:
        self.closed = True


class _BufferedFormatter:
    streaming: ClassVar[bool] = False

    def __init__(self) -> None:
        self.seen: RowSet | None = None

    def format(self, rows: RowSet) -> Iterator[str]:
        self.seen = rows
        yield "rendered"

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:  # pragma: no cover
        raise AssertionError("buffered formatter must not stream")


class _StreamingFormatter:
    streaming: ClassVar[bool] = True

    def __init__(self) -> None:
        self.blocks: list[RowSet] = []

    def format(self, rows: RowSet) -> Iterator[str]:  # pragma: no cover
        raise AssertionError("streaming formatter must not buffer")

    def format_stream(self, blocks: Iterator[RowSet]) -> Iterator[str]:
        for block in blocks:
            self.blocks.append(block)
            yield "line"


def _statement_without_preflight() -> SqlStatement:
    return SqlStatement(sql="SELECT 1", params={})


def test_statement_without_preflight_flag_runs_straight_through() -> None:
    client = FakeChClient(responses={"SELECT 1": make_rowset(["a"], [(1,)])})
    formatter = _BufferedFormatter()
    run_statement(client, _statement_without_preflight(), formatter)
    assert formatter.seen is not None
    assert client.closed is True


def test_preflight_missing_container_key_raises_unsupported_filter() -> None:
    table = "otel.otel_logs"
    preflight = build_container_preflight("nginx", table)
    client = FakeChClient(
        responses={preflight.sql: make_rowset(["key_exists", "last_seen"], [(False, None)])}
    )
    statement = SqlStatement(
        sql="SELECT * FROM otel.otel_logs",
        params={"container": "nginx"},
        meta={"container_preflight_required": True},
    )
    formatter = _BufferedFormatter()
    with pytest.raises(UnsupportedFilterError):
        run_statement(client, statement, formatter, table=table)
    assert client.closed is True


def test_preflight_existing_key_proceeds_to_main_query() -> None:
    table = "otel.otel_logs"
    preflight = build_container_preflight("nginx", table)
    main_sql = "SELECT * FROM otel.otel_logs"
    client = FakeChClient(
        responses={
            preflight.sql: make_rowset(["key_exists", "last_seen"], [(True, "2026-01-01")]),
            main_sql: make_rowset(["a"], [(1,)]),
        }
    )
    statement = SqlStatement(
        sql=main_sql, params={"container": "nginx"}, meta={"container_preflight_required": True}
    )
    formatter = _BufferedFormatter()
    run_statement(client, statement, formatter, table=table)
    assert formatter.seen is not None
    assert formatter.seen.rows == ((1,),)


def test_streaming_formatter_drives_the_streaming_client_path() -> None:
    class _StreamOnlyClient(FakeChClient):
        def execute(self, statement: SqlStatement) -> RowSet:  # pragma: no cover
            raise AssertionError("streaming path must not call execute")

    client = _StreamOnlyClient(responses={"SELECT 1": make_rowset(["a", "b"], [(1, 2), (3, 4)])})
    formatter = _StreamingFormatter()
    statement = SqlStatement(sql="SELECT 1", params={}, meta={"column_names": ("a", "b")})
    run_statement(client, statement, formatter)
    assert [block.rows for block in formatter.blocks] == [((1, 2),), ((3, 4),)]
    assert [c.name for c in formatter.blocks[0].columns] == ["a", "b"]


def test_buffered_formatter_drives_the_single_shot_path() -> None:
    class _ExecuteOnlyClient(FakeChClient):
        def stream(
            self, statement: SqlStatement
        ) -> Iterator[tuple[object, ...]]:  # pragma: no cover
            raise AssertionError("buffered path must not call stream")

    client = _ExecuteOnlyClient(responses={"SELECT 1": make_rowset(["a"], [(1,)])})
    formatter = _BufferedFormatter()
    run_statement(client, _statement_without_preflight(), formatter)
    assert formatter.seen is not None


def test_connection_closes_on_success() -> None:
    client = FakeChClient(responses={"SELECT 1": empty_rowset()})
    run_statement(client, _statement_without_preflight(), _BufferedFormatter())
    assert client.closed is True


def test_connection_closes_on_failure() -> None:
    client = FakeChClient(raises=RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        run_statement(client, _statement_without_preflight(), _BufferedFormatter())
    assert client.closed is True


class _StopFollow(Exception):
    """Ends the infinite poll loop in tests without a real sleep/cluster."""


class _SequencedClient:
    """A ChClient double that returns one canned RowSet per call, then stops the loop."""

    def __init__(self, responses: list[RowSet]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.closed = False

    def execute(self, statement: SqlStatement) -> RowSet:
        self.calls += 1
        if not self._responses:
            raise _StopFollow
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True


def test_run_follow_strips_the_hidden_cursor_column_from_narrow_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module.time, "sleep", lambda _s: None)
    batch = make_rowset(
        ["ts", "host", CURSOR_COLUMN],
        [("2026-01-01 00:00:00", "h1", "2026-01-01 00:00:00.123456")],
    )
    client = _SequencedClient([batch])
    formatter = _BufferedFormatter()
    intent = LogsIntent(filters=Filters())

    with pytest.raises(_StopFollow):
        run_follow(
            client,
            intent=intent,
            table="otel.otel_logs",
            formatter=formatter,
            since="2025-01-01 00:00:00",
        )

    assert formatter.seen is not None
    assert [c.name for c in formatter.seen.columns] == ["ts", "host"]
    assert formatter.seen.rows == (("2026-01-01 00:00:00", "h1"),)
    assert client.closed is True


def test_run_follow_advances_the_cursor_from_the_last_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module.time, "sleep", lambda _s: None)
    seen_since: list[object] = []
    original_execute = _SequencedClient.execute

    def _tracking_execute(self: _SequencedClient, statement: SqlStatement) -> RowSet:
        seen_since.append(statement.params["since"])
        return original_execute(self, statement)

    monkeypatch.setattr(_SequencedClient, "execute", _tracking_execute)
    batch = make_rowset(
        ["ts", CURSOR_COLUMN],
        [("a", "cursor-1"), ("b", "cursor-2")],
    )
    client = _SequencedClient([batch])
    formatter = _BufferedFormatter()
    intent = LogsIntent(filters=Filters())

    with pytest.raises(_StopFollow):
        run_follow(
            client, intent=intent, table="otel.otel_logs", formatter=formatter, since="start"
        )

    assert seen_since == ["start", "cursor-2"]


def test_run_follow_wide_projection_also_strips_the_hidden_cursor_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Timestamp through Python's datetime loses precision, so --full
    needs the same string cursor as narrow mode, not its own column."""
    monkeypatch.setattr(runner_module.time, "sleep", lambda _s: None)
    batch = make_rowset(
        ["Timestamp", "Body", CURSOR_COLUMN],
        [("2026-01-01 00:00:00.5", "hello", "2026-01-01 00:00:00.500000001")],
    )
    client = _SequencedClient([batch])
    formatter = _BufferedFormatter()
    intent = LogsIntent(filters=Filters(), full=True)

    with pytest.raises(_StopFollow):
        run_follow(
            client, intent=intent, table="otel.otel_logs", formatter=formatter, since="start"
        )

    assert formatter.seen is not None
    assert [c.name for c in formatter.seen.columns] == ["Timestamp", "Body"]


def test_run_follow_skips_formatting_on_an_empty_poll(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module.time, "sleep", lambda _s: None)
    client = _SequencedClient([empty_rowset()])
    formatter = _BufferedFormatter()
    intent = LogsIntent(filters=Filters())

    with pytest.raises(_StopFollow):
        run_follow(
            client, intent=intent, table="otel.otel_logs", formatter=formatter, since="start"
        )

    assert formatter.seen is None


def test_run_follow_runs_container_preflight_once_before_the_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module.time, "sleep", lambda _s: None)
    table = "otel.otel_logs"
    preflight = build_container_preflight("nginx", table)
    client = FakeChClient(
        responses={preflight.sql: make_rowset(["key_exists", "last_seen"], [(False, None)])}
    )
    intent = LogsIntent(filters=Filters(container="nginx"))

    with pytest.raises(UnsupportedFilterError):
        run_follow(
            client, intent=intent, table=table, formatter=_BufferedFormatter(), since="start"
        )


def test_run_follow_flushes_stdout_after_each_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner_module.time, "sleep", lambda _s: None)
    flushes: list[int] = []

    class _Stdout:
        def write(self, _text: str) -> int:
            return 0

        def flush(self) -> None:
            flushes.append(1)

    monkeypatch.setattr(runner_module.sys, "stdout", _Stdout())
    batch = make_rowset(["ts", CURSOR_COLUMN], [("a", "c1")])
    client = _SequencedClient([batch, batch])

    with pytest.raises(_StopFollow):
        run_follow(
            client,
            intent=LogsIntent(),
            table="otel.otel_logs",
            formatter=_BufferedFormatter(),
            since="s",
        )

    assert len(flushes) == 2


def test_run_follow_catches_up_without_sleeping_after_a_full_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(runner_module.time, "sleep", sleeps.append)
    full = make_rowset(
        ["ts", CURSOR_COLUMN], [(f"r{i}", f"c{i}") for i in range(FOLLOW_BATCH_LIMIT)]
    )
    short = make_rowset(["ts", CURSOR_COLUMN], [("x", "cx")])
    client = _SequencedClient([full, short])

    with pytest.raises(_StopFollow):
        run_follow(
            client,
            intent=LogsIntent(),
            table="otel.otel_logs",
            formatter=_BufferedFormatter(),
            since="s",
            poll_interval=0.5,
        )

    assert client.calls == 3
    assert sleeps == [0.5]


_FOLLOW_SCRIPT = """
import sys
from clickhouse_tool.cli import main
from clickhouse_tool.cli.commands import logs as logs_module
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.core.models import ColumnMeta, RowSet
from clickhouse_tool.query.builder import CURSOR_COLUMN


class EndlessClient:
    def __init__(self):
        self.polls = 0

    def execute(self, statement):
        self.polls += 1
        columns = (ColumnMeta(name="ts", ch_type=""), ColumnMeta(name=CURSOR_COLUMN, ch_type=""))
        rows = tuple((f"row-{self.polls}-{i}", f"cursor-{self.polls}-{i}") for i in range(3))
        return RowSet(columns=columns, rows=rows, row_count=3)

    def close(self):
        pass


logs_module.wiring.load_profile = lambda *_a, **_k: ResolvedProfile()
logs_module.wiring.open_client = lambda _p: EndlessClient()
logs_module.wiring.resolve_logs_table = lambda _p: "t"
logs_module.probe_columns = lambda _c, _t: frozenset()
sys.argv = ["clickhouse-tool", "logs", "--follow", "-f", "ndjson", "--interval", "INTERVAL"]
main.run()
"""


def _follow_script(tmp_path: Path, interval: str) -> Path:
    script = tmp_path / "follow.py"
    script.write_text(_FOLLOW_SCRIPT.replace("INTERVAL", interval))
    return script


def test_follow_output_reaches_a_pipe_before_the_next_poll(tmp_path: Path) -> None:
    script = _follow_script(tmp_path, "30")
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_sentry_off(),
    )
    try:
        assert proc.stdout is not None
        ready, _, _ = select.select([proc.stdout], [], [], 5)
        assert ready, "first batch did not reach the pipe; stdout is block-buffered"
        assert proc.stdout.readline().startswith(b"{")
    finally:
        proc.kill()
        proc.wait()


def test_follow_piped_into_head_exits_cleanly(tmp_path: Path) -> None:
    script = _follow_script(tmp_path, "0.05")
    result = subprocess.run(  # noqa: S603
        ["/bin/sh", "-c", f'"{sys.executable}" "{script}" | head -5'],
        capture_output=True,
        text=True,
        timeout=20,
        env=_sentry_off(),
        check=False,
    )

    assert result.returncode == 0
    assert len(result.stdout.splitlines()) == 5
    assert "Traceback" not in result.stderr
    assert "BrokenPipe" not in result.stderr


def _sentry_off() -> dict[str, str]:
    return {**os.environ, "CLICKHOUSE_TOOL_SENTRY_DSN": ""}


def test_run_follow_arrival_mode_uses_the_tuple_cursor_and_strips_both_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module.time, "sleep", lambda _s: None)
    seen: list[tuple[object, object]] = []
    original_execute = _SequencedClient.execute

    def _tracking_execute(self: _SequencedClient, statement: SqlStatement) -> RowSet:
        seen.append((statement.params.get("since_ins"), statement.params.get("since_ts")))
        return original_execute(self, statement)

    monkeypatch.setattr(_SequencedClient, "execute", _tracking_execute)
    batch = make_rowset(
        ["ts", "msg", ARRIVAL_CURSOR_COLUMN, CURSOR_COLUMN],
        [
            ("a", "m1", "2026-11-06 21:00:01", "2026-11-06 20:59:40.5"),
            ("b", "m2", "2026-11-06 21:00:01", "2026-11-06 20:59:41.5"),
        ],
    )
    client = _SequencedClient([batch])
    formatter = _BufferedFormatter()

    with pytest.raises(_StopFollow):
        run_follow(
            client,
            intent=LogsIntent(),
            table="otel.otel_logs",
            formatter=formatter,
            since=("2026-11-06 20:59:58", "1970-01-01 00:00:00.000000000"),
            arrival=True,
        )

    assert seen == [
        ("2026-11-06 20:59:58", "1970-01-01 00:00:00.000000000"),
        ("2026-11-06 21:00:01", "2026-11-06 20:59:41.5"),
    ]
    assert formatter.seen is not None
    assert [c.name for c in formatter.seen.columns] == ["ts", "msg"]


def test_run_follow_applies_the_row_transform_before_formatting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner_module.time, "sleep", lambda _s: None)
    batch = make_rowset(["msg", CURSOR_COLUMN], [("x", "c1")])
    client = _SequencedClient([batch])
    formatter = _BufferedFormatter()

    def upper(rows: RowSet) -> RowSet:
        return RowSet(
            columns=rows.columns,
            rows=tuple((r[0].upper(),) for r in rows.rows),
            row_count=rows.row_count,
        )

    with pytest.raises(_StopFollow):
        run_follow(
            client,
            intent=LogsIntent(),
            table="t",
            formatter=formatter,
            since="s",
            row_transform=upper,
        )

    assert formatter.seen is not None
    assert formatter.seen.rows == (("X",),)
