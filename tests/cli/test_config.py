"""Tests for the config verb: no AWS contact, provenance, and redaction."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli.main import app
from clickhouse_tool.core.config import ResolvedProfile, SsmRef

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_succeeds_with_no_credentials_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.commands.config as config_module

    monkeypatch.setattr(config_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile())
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0, result.stdout


def test_no_parameter_store_call_is_attempted(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.commands.config as config_module

    def _boom_if_called(*_a: object, **_k: object) -> None:  # pragma: no cover
        raise AssertionError("config verb must never call SSM")

    monkeypatch.setattr(config_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile())
    monkeypatch.setattr("clickhouse_tool.core.ssm.materialise_secrets", _boom_if_called)
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0, result.stdout


def test_every_field_shows_its_source_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.commands.config as config_module

    resolved = ResolvedProfile(active_profile="pilot", sources={"host": "profile: pilot"})
    monkeypatch.setattr(config_module.wiring, "load_profile", lambda _p, **_k: resolved)
    result = runner.invoke(app, ["config"])
    payload = json.loads(result.stdout)
    assert payload["sources"]["host"] == "profile: pilot"


def test_secret_fields_show_shape_description_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.commands.config as config_module

    resolved = ResolvedProfile(user=SsmRef(ssm="/x/y"), password="literal-secret")  # noqa: S106
    monkeypatch.setattr(config_module.wiring, "load_profile", lambda _p, **_k: resolved)
    result = runner.invoke(app, ["config"])
    assert "literal-secret" not in result.stdout
    payload = json.loads(result.stdout)
    assert payload["user"] == "(unresolved, ssm:/x/y)"
    assert payload["password"] == "(literal, 14 chars)"  # noqa: S105
