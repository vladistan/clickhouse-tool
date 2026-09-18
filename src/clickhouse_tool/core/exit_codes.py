"""Pinned exit codes for clickhouse-tool.

Every typed error maps to exactly one code. The mapping is permanent;
``tests/test_exit_codes.py`` pins every value.
"""

from enum import IntEnum


class ExitCode(IntEnum):
    """Exit codes for clickhouse-tool commands."""

    SUCCESS = 0
    GENERAL_ERROR = 1
    USAGE_ERROR = 2
    CONFIG_ERROR = 3
    CONNECTION_FAILED = 4
    AUTH_FAILED = 5
    QUERY_TIMEOUT = 6
    RESULT_TOO_LARGE = 7
    SERVER_RESOURCE_ERROR = 8
    PERMISSION_DENIED = 9
    SCHEMA_ERROR = 10
    UNSUPPORTED_FILTER = 11
    SERVER_ERROR = 12
