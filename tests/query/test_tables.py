"""Tests for the table allow-list, at 100% branch coverage."""

import pytest

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.query.tables import SYSTEM_TABLES, validate_table

pytestmark = pytest.mark.unit


def test_otel_table_matching_identifier_pattern_is_accepted() -> None:
    assert validate_table("otel.logs") == "otel.logs"


@pytest.mark.parametrize("table", sorted(SYSTEM_TABLES))
def test_exactly_the_seven_system_tables_are_accepted(table: str) -> None:
    assert validate_table(table) == table


def test_exactly_seven_system_tables_are_enumerated() -> None:
    assert len(SYSTEM_TABLES) == 7


@pytest.mark.parametrize(
    "table",
    [
        "system.users",
        "otel..logs",
        "otel.1logs",
        "otherdb.logs",
        "; DROP TABLE otel.logs",
        "",
    ],
)
def test_a_rejected_table_raises_before_anything_else_happens(table: str) -> None:
    with pytest.raises(ConfigError):
        validate_table(table)
