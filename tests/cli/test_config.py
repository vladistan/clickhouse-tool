"""Tests for the config verb: no AWS contact, provenance, and redaction."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_aws_settings_show_the_winning_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import clickhouse_tool.core.config as config_module

    (tmp_path / "user.toml").write_text(
        '[profiles.ars]\nhost = "h"\naws_profile = "apps"\naws_region = "eu-central-1"\n'
    )
    monkeypatch.setattr(config_module, "USER_CONFIG_PATH", tmp_path / "user.toml")
    monkeypatch.setattr(config_module, "PROJECT_CONFIG_PATH", tmp_path / "none.toml")
    monkeypatch.setenv("AWS_PROFILE", "dev")
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    result = runner.invoke(app, ["config", "--profile", "ars"])

    assert result.exit_code == 0, result.stdout
    shown = json.loads(result.stdout)
    assert shown["aws_profile"] == "dev"
    assert shown["sources"]["aws_profile"] == "env: AWS_PROFILE"
    assert shown["aws_region"] == "eu-central-1"
    assert shown["sources"]["aws_region"] == "profile: ars"


def test_aws_settings_default_to_the_boto3_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.commands.config as config_module

    monkeypatch.setattr(config_module.wiring, "load_profile", lambda _p, **_k: ResolvedProfile())
    result = runner.invoke(app, ["config"])
    shown = json.loads(result.stdout)
    assert shown["aws_profile"] is None
    assert "aws_profile" not in shown["sources"]
