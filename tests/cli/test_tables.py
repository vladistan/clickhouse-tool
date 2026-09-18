"""Tests for the tables verb: enumerating the allow-list."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli.main import app
from clickhouse_tool.core.config import ResolvedProfile
from clickhouse_tool.core.models import SqlStatement

pytestmark = pytest.mark.unit

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_real_connection(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    import clickhouse_tool.cli.commands.tables as tables_module

    captured: dict[str, object] = {}
    monkeypatch.setattr(
        tables_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile(database="otel")
    )
    monkeypatch.setattr(tables_module.wiring, "open_client", lambda _p: object())

    def _fake_run_statement(_client: object, statement: object, _formatter: object, **_kwargs: object) -> None:
        captured["statement"] = statement

    monkeypatch.setattr(tables_module, "run_statement", _fake_run_statement)
    return captured


def test_tables_binds_the_resolved_profile_database(_no_real_connection: dict[str, object]) -> None:
    result = runner.invoke(app, ["tables"])
    assert result.exit_code == 0, result.stdout
    statement = _no_real_connection["statement"]
    assert isinstance(statement, SqlStatement)
    assert statement.params["database"] == "otel"


def test_tables_connects_unlike_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unlike ``config``, ``tables`` queries the live cluster -- it opens a client."""
    import clickhouse_tool.cli.commands.tables as tables_module

    called = {"opened": False}
    monkeypatch.setattr(
        tables_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile(database="otel")
    )

    def _fake_open_client(_profile: object) -> object:
        called["opened"] = True
        return object()

    monkeypatch.setattr(tables_module.wiring, "open_client", _fake_open_client)
    monkeypatch.setattr(tables_module, "run_statement", lambda *_a, **_k: None)
    result = runner.invoke(app, ["tables"])
    assert result.exit_code == 0, result.stdout
    assert called["opened"] is True
