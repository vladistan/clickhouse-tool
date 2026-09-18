"""Tests for intent dataclasses."""

import pytest

from clickhouse_tool.query.intents import CountIntent, Filters, LogsIntent

pytestmark = pytest.mark.unit


def test_logs_intent_round_trips_every_filter_flag() -> None:
    filters = Filters(
        host="firewall7",
        service="api",
        namespace="prod",
        container="nginx",
        level="warn",
        time_range="15m",
        search="refused",
    )
    intent = LogsIntent(
        filters=filters,
        columns=("ts", "level", "msg"),
        full=True,
        raw=True,
        sort="@timestamp:desc",
        limit=50,
    )

    assert intent.filters == filters
    assert intent.columns == ("ts", "level", "msg")
    assert intent.full is True
    assert intent.raw is True
    assert intent.sort == "@timestamp:desc"
    assert intent.limit == 50


def test_count_intent_is_a_distinct_type_not_a_mutated_logs_intent() -> None:
    filters = Filters(host="firewall7", search="refused")
    logs_intent = LogsIntent(filters=filters, columns=("ts",), limit=10, sort="ts:asc")

    count_intent = CountIntent.from_logs_intent(logs_intent)

    assert isinstance(count_intent, CountIntent)
    assert not isinstance(count_intent, LogsIntent)
    assert count_intent.filters == filters
    assert not hasattr(count_intent, "columns")
    assert not hasattr(count_intent, "limit")
    assert not hasattr(count_intent, "sort")
