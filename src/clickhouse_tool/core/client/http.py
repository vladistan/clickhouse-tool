"""ClickHouse client over HTTP (clickhouse-connect, port 8123).

Only the constructor imports ``clickhouse_connect``, so a bare import
of this module never pulls it in -- same discipline as ``native.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from clickhouse_tool.core.errors import ClickhouseToolError, ConnectionFailed, map_server_code
from clickhouse_tool.core.models import ColumnMeta, RowSet, SqlStatement

_CODE_RE = re.compile(r"Code:\s*(\d+)")


class HttpChClient:
    """ChClient over clickhouse-connect's HTTP transport."""

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
        query_timeout: float = 60.0,
    ) -> None:
        import clickhouse_connect

        self._client = clickhouse_connect.get_client(
            host=host,
            port=port,
            database=database,
            username=user,
            password=password,
            secure=secure,
            connect_timeout=connect_timeout,
            settings={"readonly": 2, "max_execution_time": query_timeout},
        )

    def ping(self) -> None:
        try:
            alive = self._client.ping()
        except Exception as exc:
            raise translate_http_error(exc) from exc
        if not alive:
            raise ConnectionFailed("HTTP backend ping returned false")

    def execute(self, statement: SqlStatement) -> RowSet:
        try:
            result = self._client.query(
                statement.sql, parameters=statement.params, settings=statement.settings or None
            )
        except Exception as exc:
            raise translate_http_error(exc) from exc
        col_meta = tuple(
            ColumnMeta(name=name, ch_type=str(ch_type))
            for name, ch_type in zip(result.column_names, result.column_types, strict=True)
        )
        rows = tuple(tuple(row) for row in result.result_rows)
        return RowSet(columns=col_meta, rows=rows, row_count=len(rows))

    def stream(self, statement: SqlStatement) -> Iterator[tuple[Any, ...]]:
        try:
            ctx = self._client.query_rows_stream(
                statement.sql, parameters=statement.params, settings=statement.settings or None
            )
        except Exception as exc:
            raise translate_http_error(exc) from exc
        try:
            with ctx:
                for row in ctx:
                    yield tuple(row)
        except Exception as exc:
            raise translate_http_error(exc) from exc

    def close(self) -> None:
        self._client.close()


def translate_http_error(exc: Exception) -> ClickhouseToolError:
    """Translate a clickhouse-connect exception into the shared typed hierarchy.

    Order: the parsed ``code`` attribute, then a ``Code: NNN`` text
    prefix. A failure with no code becomes :class:`ConnectionFailed`.
    """
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return map_server_code(code, str(exc))
    match = _CODE_RE.search(str(exc))
    if match:
        return map_server_code(int(match.group(1)), str(exc))
    return ConnectionFailed(str(exc))
