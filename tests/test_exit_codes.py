"""Tests for pinned exit codes."""

import pytest

from clickhouse_tool.core.exit_codes import ExitCode

pytestmark = pytest.mark.unit

# Every exit code maps to a documented number. Breaking changes are not
# allowed: add new members, never renumber existing ones.
_PINNED = {
    "SUCCESS": 0,
    "GENERAL_ERROR": 1,
    "USAGE_ERROR": 2,
    "CONFIG_ERROR": 3,
    "CONNECTION_FAILED": 4,
    "AUTH_FAILED": 5,
    "QUERY_TIMEOUT": 6,
    "RESULT_TOO_LARGE": 7,
    "SERVER_RESOURCE_ERROR": 8,
    "PERMISSION_DENIED": 9,
    "SCHEMA_ERROR": 10,
    "UNSUPPORTED_FILTER": 11,
    "SERVER_ERROR": 12,
}


@pytest.mark.parametrize("name,code", _PINNED.items())
def test_exit_codes_match_pinned_values(name: str, code: int) -> None:
    assert getattr(ExitCode, name) == code


def test_only_pinned_exit_codes_exist() -> None:
    actual = {name: member.value for name, member in ExitCode.__members__.items()}
    assert actual == _PINNED
