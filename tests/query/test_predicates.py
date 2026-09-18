"""Tests for per-flag predicate builders."""

import pytest

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.query.predicates import (
    build_search_predicate,
    container_predicate,
    host_predicate,
    level_predicate,
    namespace_predicate,
    service_predicate,
    since_predicate,
    time_predicate,
)

pytestmark = pytest.mark.unit


def test_host_predicate_produces_bound_equality() -> None:
    predicate = host_predicate("firewall7")
    assert "HostName =" in predicate.sql
    assert "firewall7" not in predicate.sql
    assert "firewall7" in predicate.params.values()


def test_service_predicate_produces_bound_equality() -> None:
    predicate = service_predicate("api")
    assert "ServiceName =" in predicate.sql
    assert "api" not in predicate.sql
    assert "api" in predicate.params.values()


def test_namespace_predicate_produces_bound_equality() -> None:
    predicate = namespace_predicate("prod")
    assert "Namespace =" in predicate.sql
    assert "prod" not in predicate.sql
    assert "prod" in predicate.params.values()


@pytest.mark.parametrize(
    "level,expected_threshold",
    [
        ("trace", 1),
        ("debug", 5),
        ("info", 9),
        ("warn", 13),
        ("error", 17),
        ("fatal", 21),
    ],
)
def test_level_predicate_uses_exact_severity_ladder(level: str, expected_threshold: int) -> None:
    predicate = level_predicate(level)
    assert predicate.params["level"] == expected_threshold
    assert "SeverityNumber >=" in predicate.sql


def test_level_predicate_rejects_unknown_level() -> None:
    with pytest.raises(ConfigError):
        level_predicate("critical")


def test_time_predicate_emits_timestamp_and_partition_companion() -> None:
    predicate = time_predicate("15m")
    assert "Timestamp >=" in predicate.sql
    assert "toDate(Timestamp) >=" in predicate.sql
    assert predicate.params["tr_count"] == 15


def test_time_predicate_honours_an_alternate_column() -> None:
    predicate = time_predicate("15m", column="TimeUnix")
    assert "TimeUnix >=" in predicate.sql
    assert "Timestamp" not in predicate.sql


def test_since_predicate_binds_the_cursor_as_a_strict_lower_bound() -> None:
    predicate = since_predicate("2026-01-01 00:00:00")
    assert predicate.sql == "Timestamp > %(since)s"
    assert predicate.params == {"since": "2026-01-01 00:00:00"}


def test_search_single_token_selects_token_index_strategy() -> None:
    predicate, strategy = build_search_predicate("connection")
    assert strategy == "token"
    assert "hasToken" in predicate.sql
    assert predicate.params["search"] == "connection"


@pytest.mark.parametrize("term", ["ab", "two words", "conn-refused", "conn's"])
def test_non_token_term_falls_back_to_substring_match(term: str) -> None:
    predicate, strategy = build_search_predicate(term)
    assert strategy == "ilike"
    assert "ILIKE" in predicate.sql


@pytest.mark.parametrize("term", ["100%", "under_score", "back\\slash", "quo'te"])
def test_special_characters_in_search_term_are_bound_not_escaped(term: str) -> None:
    predicate, _strategy = build_search_predicate(term)
    assert term not in predicate.sql
    bound_values = list(predicate.params.values())
    assert any(term in value for value in bound_values)


def test_container_predicate_produces_map_key_predicate() -> None:
    predicate = container_predicate("nginx")
    assert "LogAttributes['container_name']" in predicate.sql
    assert "nginx" not in predicate.sql
    assert "nginx" in predicate.params.values()


def test_no_predicate_ever_emits_the_forbidden_or_shape() -> None:
    fragments = [
        host_predicate("h").sql,
        service_predicate("s").sql,
        namespace_predicate("n").sql,
        container_predicate("c").sql,
        level_predicate("warn").sql,
        time_predicate("15m").sql,
        build_search_predicate("term")[0].sql,
        build_search_predicate("a b")[0].sql,
    ]
    for fragment in fragments:
        assert " OR " not in fragment
