"""Typed exception hierarchy plus the shared server-code translation table.

Both backend clients feed :func:`map_server_code`. No other module may
define its own code table or exception hierarchy.
"""

from __future__ import annotations

import logging

from clickhouse_tool.core.exit_codes import ExitCode

logger = logging.getLogger(__name__)


class ClickhouseToolError(Exception):
    """Base for every typed error this tool raises.

    ``str(error)`` must never contain a secret value -- only provenance
    (a config key, an SSM path) may appear, never a resolved credential.
    """

    exit_code: ExitCode = ExitCode.GENERAL_ERROR

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


class ConfigError(ClickhouseToolError):
    """Raised client-side: a profile, config file, or flag combination is invalid."""

    exit_code = ExitCode.CONFIG_ERROR


class ConnectionFailed(ClickhouseToolError):
    """Raised client-side: the selected backend could not reach the server."""

    exit_code = ExitCode.CONNECTION_FAILED


class UnsupportedFilterError(ClickhouseToolError):
    """Raised client-side: a filter has no exporter column for this data (e.g. -C preflight)."""

    exit_code = ExitCode.UNSUPPORTED_FILTER


class AuthFailed(ClickhouseToolError):
    """Server rejected the credentials (CH codes 192, 193, 516)."""

    exit_code = ExitCode.AUTH_FAILED


class QueryTimeout(ClickhouseToolError):
    """Server-side execution time limit exceeded (CH codes 159, 160)."""

    exit_code = ExitCode.QUERY_TIMEOUT


class ResultTooLarge(ClickhouseToolError):
    """Server-side result row/byte limit exceeded (CH code 396)."""

    exit_code = ExitCode.RESULT_TOO_LARGE


class ServerResourceError(ClickhouseToolError):
    """Server-side memory/resource limit exceeded (CH codes 241, 202, 203)."""

    exit_code = ExitCode.SERVER_RESOURCE_ERROR


class PermissionDenied(ClickhouseToolError):
    """Server rejected the operation as unauthorized (CH codes 164, 497)."""

    exit_code = ExitCode.PERMISSION_DENIED


class SchemaError(ClickhouseToolError):
    """Server reported an unknown table/column or malformed column metadata
    (CH codes 60, 47, 81)."""

    exit_code = ExitCode.SCHEMA_ERROR


class ServerError(ClickhouseToolError):
    """Any ClickHouse server error code not present in the shared table.

    Keeps the numeric code and message verbatim, and logs the unmapped
    code at warn level so someone can add it to the table later.
    """

    exit_code = ExitCode.SERVER_ERROR


# CH numeric error code -> typed exception. Every entry here is covered by a
# parametrized test asserting 100% of the table maps correctly.
_CODE_TABLE: dict[int, type[ClickhouseToolError]] = {
    60: SchemaError,
    47: SchemaError,
    81: SchemaError,
    159: QueryTimeout,
    160: QueryTimeout,
    164: PermissionDenied,
    497: PermissionDenied,
    192: AuthFailed,
    193: AuthFailed,
    516: AuthFailed,
    241: ServerResourceError,
    202: ServerResourceError,
    203: ServerResourceError,
    396: ResultTooLarge,
}


def map_server_code(code: int, message: str) -> ClickhouseToolError:
    """Translate a ClickHouse numeric error code into its typed exception.

    An unmapped code produces :class:`ServerError` and logs a warning,
    rather than swallowing the code or guessing at it.
    """
    exc_type = _CODE_TABLE.get(code)
    if exc_type is None:
        logger.warning("unmapped ClickHouse error code %s: %s", code, message)
        return ServerError(message, code=code)
    return exc_type(message, code=code)
