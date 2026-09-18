"""Tests for sort alias canonicalisation."""

import pytest

from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.query.sort import DEFAULT_SORT, canonicalise_sort

pytestmark = pytest.mark.unit


def test_es_style_alias_canonicalises() -> None:
    assert canonicalise_sort("@timestamp:desc") == "Timestamp DESC"


def test_severity_number_alias_canonicalises() -> None:
    assert canonicalise_sort("severity_number:desc") == "SeverityNumber DESC"


def test_native_column_name_passes_through_unchanged() -> None:
    assert canonicalise_sort("HostName") == "HostName"


def test_native_column_with_direction_passes_through_unchanged() -> None:
    assert canonicalise_sort("Timestamp DESC") == "Timestamp DESC"


def test_unknown_sort_name_is_rejected_listing_accepted_names() -> None:
    with pytest.raises(ConfigError) as exc_info:
        canonicalise_sort("bogus_field")
    assert "bogus_field" in str(exc_info.value)


def test_default_sort_is_timestamp_descending() -> None:
    assert canonicalise_sort(None) == DEFAULT_SORT == "Timestamp DESC"


def test_injection_payload_after_valid_direction_is_rejected() -> None:
    with pytest.raises(ConfigError):
        canonicalise_sort("Timestamp DESC; DROP TABLE otel_logs")


def test_injection_payload_after_valid_column_is_rejected() -> None:
    with pytest.raises(ConfigError):
        canonicalise_sort("HostName; DROP TABLE otel_logs")


def test_unrecognised_direction_after_valid_column_is_rejected() -> None:
    with pytest.raises(ConfigError):
        canonicalise_sort("Timestamp SIDEWAYS")


def test_empty_string_sort_is_rejected_not_a_crash() -> None:
    with pytest.raises(ConfigError):
        canonicalise_sort("")
