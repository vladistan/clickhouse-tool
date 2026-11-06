"""ClickHouse client over the native TCP protocol (clickhouse-driver, port 9000).

Only the constructor imports ``clickhouse_driver``, never module scope,
so a bare import of this module never requires the driver package.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Iterator
from typing import Any

from clickhouse_tool.core.errors import (
    ClickhouseToolError,
    ConnectionFailed,
    SchemaError,
    map_server_code,
)
from clickhouse_tool.core.models import ColumnMeta, RowSet, SqlStatement

_CODE_RE = re.compile(r"Code:\s*(\d+)")


def _escape_literal_percent_signs(sql: str, params: dict[str, Any]) -> str:
    """Double every ``%`` that is not one of our own ``%(name)s`` placeholders.

    clickhouse-driver substitutes via Python's ``%`` operator. Any other
    literal ``%`` needs ``%%`` or the substitution raises.
    """
    placeholder_re = re.compile(
        "%(" + "|".join(re.escape(f"({name})s") for name in params) + ")" if params else "(?!)"
    )
    parts = []
    last_end = 0
    for match in placeholder_re.finditer(sql):
        parts.append(sql[last_end : match.start()].replace("%", "%%"))
        parts.append(match.group())
        last_end = match.end()
    parts.append(sql[last_end:].replace("%", "%%"))
    return "".join(parts)


def build_query_settings(query_timeout: float | None) -> dict[str, Any]:
    """Assemble the settings applied to every native execution.

    Always carries the mandatory ``readonly=2`` write barrier. Threads
    ``query_timeout`` into ``max_execution_time``, matching the HTTP
    transport's setting name.
    """
    settings: dict[str, Any] = {"readonly": 2}
    if query_timeout is not None:
        settings["max_execution_time"] = query_timeout
    return settings


class NativeChClient:
    """ChClient over clickhouse-driver's native TCP protocol.

    Always asks for ``readonly=2`` -- the sole write barrier. Doubles
    stray ``%`` characters for the driver's substitution mechanism;
    semantics stay the same.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        secure: bool = False,
        connect_timeout: float = 10.0,
        send_receive_timeout: float = 60.0,
        query_timeout: float | None = None,
    ) -> None:
        from clickhouse_driver import Client

        self.settings = build_query_settings(query_timeout)
        self._client = Client(
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            secure=secure,
            connect_timeout=connect_timeout,
            send_receive_timeout=send_receive_timeout,
            settings=self.settings,
        )

    def ping(self) -> None:
        try:
            self._client.execute("SELECT 1")
        except Exception as exc:
            raise translate_native_error(exc) from exc

    def execute(self, statement: SqlStatement) -> RowSet:
        sql = _escape_literal_percent_signs(statement.sql, statement.params)
        try:
            rows, columns = self._client.execute(
                sql, statement.params, with_column_types=True, settings=statement.settings or None
            )
        except Exception as exc:
            raise translate_native_error(exc) from exc
        col_meta = tuple(ColumnMeta(name=name, ch_type=ch_type) for name, ch_type in columns)
        row_tuples = tuple(tuple(row) for row in rows)
        return RowSet(columns=col_meta, rows=row_tuples, row_count=len(row_tuples))

    def stream(self, statement: SqlStatement) -> Iterator[tuple[Any, ...]]:
        sql = _escape_literal_percent_signs(statement.sql, statement.params)
        iterator = self._client.execute_iter(
            sql, statement.params, with_column_types=True, settings=statement.settings or None
        )
        try:
            try:
                first = next(iterator)
            except StopIteration:
                return
            except Exception as exc:
                raise translate_native_error(exc) from exc
            if not _is_column_header(first):
                raise SchemaError(
                    "native backend did not return column metadata as the first streamed item"
                )
            try:
                for row in iterator:
                    yield tuple(row)
            except Exception as exc:
                raise translate_native_error(exc) from exc
        finally:
            _drain_and_disconnect(iterator, self._client)

    def close(self) -> None:
        self._client.disconnect()


def _is_column_header(item: Any) -> bool:
    """True when ``item`` is ``[(name, type), ...]`` rather than a data row.

    The native driver's documented quirk: with ``with_column_types=True``,
    ``execute_iter`` yields the column description first, never a row.
    """
    return isinstance(item, list) and all(
        isinstance(pair, tuple) and len(pair) == 2 and isinstance(pair[0], str) for pair in item
    )


def _drain_and_disconnect(iterator: Iterator[Any], client: Any) -> None:
    """Exhaust whatever remains of ``iterator`` and disconnect.

    An abandoned native stream leaves the connection mid-block unless
    drained. Runs on every exit path, so the next query stays clean.
    """
    with contextlib.suppress(Exception):  # best-effort cleanup, never masks the real failure
        for _ in iterator:
            pass
    with contextlib.suppress(Exception):  # best-effort cleanup, never masks the real failure
        client.disconnect()


def translate_native_error(exc: Exception) -> ClickhouseToolError:
    """Translate a clickhouse-driver exception into the shared typed hierarchy.

    Network-lost, timeout, and packet shapes map to
    :class:`ConnectionFailed` first -- the driver reuses server codes.
    Otherwise ``map_server_code`` decides.
    """
    from clickhouse_driver.errors import (
        NetworkError,
        SocketTimeoutError,
        UnexpectedPacketFromServerError,
    )

    if isinstance(exc, (NetworkError, SocketTimeoutError, UnexpectedPacketFromServerError)):
        return ConnectionFailed(str(exc))
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return map_server_code(code, str(exc))
    match = _CODE_RE.search(str(exc))
    if match:
        return map_server_code(int(match.group(1)), str(exc))
    return ConnectionFailed(str(exc))
