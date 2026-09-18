"""Tests for the display-timezone resolution used by `logs`."""

from __future__ import annotations

import os

import pytest

from clickhouse_tool.core.timezone import local_timezone_name, resolve_display_timezone

pytestmark = pytest.mark.unit


def test_utc_flag_always_wins_regardless_of_configured_value() -> None:
    assert resolve_display_timezone(utc=True, configured="America/New_York") == "UTC"
    assert resolve_display_timezone(utc=True, configured="local") == "UTC"


def test_local_literal_resolves_to_the_machine_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "clickhouse_tool.core.timezone.local_timezone_name", lambda: "America/Chicago"
    )
    assert resolve_display_timezone(utc=False, configured="local") == "America/Chicago"


def test_an_explicit_configured_zone_is_used_verbatim() -> None:
    assert resolve_display_timezone(utc=False, configured="Europe/Berlin") == "Europe/Berlin"


def test_local_timezone_name_parses_the_localtime_symlink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        os.path, "realpath", lambda _path: "/usr/share/zoneinfo/America/Los_Angeles"
    )
    assert local_timezone_name() == "America/Los_Angeles"


def test_local_timezone_name_falls_back_to_utc_without_a_zoneinfo_symlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(os.path, "realpath", lambda _path: "/etc/localtime")
    assert local_timezone_name() == "UTC"


def test_local_timezone_name_falls_back_to_utc_on_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(_path: str) -> str:
        raise OSError("no such path")

    monkeypatch.setattr(os.path, "realpath", _raise)
    assert local_timezone_name() == "UTC"
