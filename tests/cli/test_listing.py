"""Tests for the list/lift verbs: allow-list enforcement and lift's default format."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli.main import app
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.formatters import JsonFormatter, TableFormatter, ToonFormatter

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_real_connection(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    import clickhouse_tool.cli.commands.listing as listing_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        listing_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile(default_format="toon")
    )
    monkeypatch.setattr(listing_module.wiring, "open_client", lambda _p: object())

    def _fake_run_statement(_client: object, statement: object, formatter: object, **kwargs: object) -> None:
        captured["statement"] = statement
        captured["formatter"] = formatter

    monkeypatch.setattr(listing_module, "run_statement", _fake_run_statement)
    return captured


def test_allowed_table_succeeds(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["list", "system.parts"])
    assert result.exit_code == 0, result.stdout


def test_non_allow_listed_table_fails_listing_accepted_set() -> None:
    result = runner.invoke(app, ["list", "system.users"])
    assert result.exit_code != 0
    assert result.exception is not None
    assert "system.users" in str(result.exception)


def test_lift_selects_nested_output_format_when_no_flag_given(
    _no_real_connection: dict[str, object],
) -> None:
    result = runner.invoke(app, ["lift", "system.parts"])
    assert result.exit_code == 0, result.stdout
    assert isinstance(_no_real_connection["formatter"], JsonFormatter)


def test_lift_explicit_format_flag_still_wins(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["lift", "system.parts", "-f", "table"])
    assert result.exit_code == 0, result.stdout
    assert isinstance(_no_real_connection["formatter"], TableFormatter)


def test_list_uses_the_profile_default_format_when_no_flag_given(
    _no_real_connection: dict[str, object],
) -> None:
    result = runner.invoke(app, ["list", "system.parts"])
    assert result.exit_code == 0, result.stdout
    assert isinstance(_no_real_connection["formatter"], ToonFormatter)
