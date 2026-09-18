"""Tests for TOML layer loading, precedence merge, and provenance."""

from __future__ import annotations

from pathlib import Path

import pytest

from clickhouse_tool.core.config import (
    AppConfig,
    Profile,
    ResolvedProfile,
    SsmRef,
    load_layers,
    resolve_profile,
)
from clickhouse_tool.core.errors import ConfigError

pytestmark = pytest.mark.unit


def _missing(tmp_path: Path, name: str) -> Path:
    return tmp_path / name


class TestLoadLayers:
    def test_no_files_returns_defaults(self, tmp_path: Path) -> None:
        config = load_layers(
            project_path=_missing(tmp_path, "project.toml"),
            user_path=_missing(tmp_path, "user.toml"),
        )
        assert config == AppConfig()

    def test_user_level_only(self, tmp_path: Path) -> None:
        user_file = tmp_path / "user.toml"
        user_file.write_text('default_profile = "pilot"\n[profiles.pilot]\nhost = "h1"\n')
        config = load_layers(project_path=_missing(tmp_path, "project.toml"), user_path=user_file)
        assert config.default_profile == "pilot"
        assert config.profiles["pilot"].host == "h1"

    def test_project_local_overrides_user_level_field_by_field(self, tmp_path: Path) -> None:
        user_file = tmp_path / "user.toml"
        user_file.write_text(
            '[profiles.pilot]\nhost = "user-host"\nport = 9000\ndatabase = "userdb"\n'
        )
        project_file = tmp_path / "project.toml"
        project_file.write_text('[profiles.pilot]\nhost = "project-host"\n')

        config = load_layers(project_path=project_file, user_path=user_file)

        assert config.profiles["pilot"].host == "project-host"
        assert config.profiles["pilot"].port == 9000
        assert config.profiles["pilot"].database == "userdb"

    def test_malformed_toml_raises_config_error(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.toml"
        bad_file.write_text("not [ valid toml")
        with pytest.raises(ConfigError, match="Malformed TOML"):
            load_layers(project_path=_missing(tmp_path, "p.toml"), user_path=bad_file)

    def test_invalid_config_shape_raises_config_error(self, tmp_path: Path) -> None:
        bad_file = tmp_path / "bad.toml"
        bad_file.write_text('[profiles.pilot]\nport = "not-an-int"\n')
        with pytest.raises(ConfigError, match="Invalid configuration"):
            load_layers(project_path=_missing(tmp_path, "p.toml"), user_path=bad_file)

    def test_ssm_ref_parses_inside_profile(self, tmp_path: Path) -> None:
        user_file = tmp_path / "user.toml"
        user_file.write_text('[profiles.pilot]\n[profiles.pilot.password]\nssm = "/a/b"\n')
        config = load_layers(project_path=_missing(tmp_path, "p.toml"), user_path=user_file)
        password = config.profiles["pilot"].password
        assert isinstance(password, SsmRef)
        assert password.ssm == "/a/b"


class TestResolveProfile:
    def _config(self) -> AppConfig:
        return AppConfig(
            default_profile="pilot",
            profiles={
                "pilot": Profile(host="pilot-host", port=9000, database="otel"),
                "pilot-http": Profile(host="pilot-host", port=8123, transport="http"),
            },
        )

    def test_defaults_only(self) -> None:
        resolved = resolve_profile(AppConfig())
        assert resolved.host == "localhost"
        assert resolved.sources["host"] == "default"
        assert resolved.active_profile is None

    def test_default_profile_used_when_none_named(self) -> None:
        resolved = resolve_profile(self._config())
        assert resolved.active_profile == "pilot"
        assert resolved.host == "pilot-host"
        assert resolved.sources["host"] == "profile: pilot"

    def test_named_profile_overrides_default_profile(self) -> None:
        resolved = resolve_profile(self._config(), profile_name="pilot-http")
        assert resolved.active_profile == "pilot-http"
        assert resolved.port == 8123
        assert resolved.transport == "http"

    def test_unknown_profile_raises_and_lists_available(self) -> None:
        with pytest.raises(ConfigError, match="pilot, pilot-http"):
            resolve_profile(self._config(), profile_name="nope")

    def test_env_overrides_profile(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLICKHOUSE_TOOL_HOST", "env-host")
        resolved = resolve_profile(self._config())
        assert resolved.host == "env-host"
        assert resolved.sources["host"] == "env: CLICKHOUSE_TOOL_HOST"

    def test_env_port_must_be_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLICKHOUSE_TOOL_PORT", "not-a-number")
        with pytest.raises(ConfigError, match="Invalid CLICKHOUSE_TOOL_PORT"):
            resolve_profile(self._config())

    def test_env_secure_coerces_truthy_strings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLICKHOUSE_TOOL_SECURE", "true")
        resolved = resolve_profile(self._config())
        assert resolved.secure is True

    def test_cli_override_beats_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLICKHOUSE_TOOL_HOST", "env-host")
        resolved = resolve_profile(self._config(), host="cli-host")
        assert resolved.host == "cli-host"
        assert resolved.sources["host"] == "cli: --host"

    def test_cli_override_beats_profile_beats_default(self) -> None:
        resolved = resolve_profile(self._config(), port=1234)
        assert resolved.port == 1234
        assert resolved.sources["port"] == "cli: --port"

    def test_ssm_ref_left_unresolved(self) -> None:
        config = AppConfig(
            profiles={"pilot": Profile(password=SsmRef(ssm="/a/b"))},
        )
        resolved = resolve_profile(config, profile_name="pilot")
        assert isinstance(resolved.password, SsmRef)

    def test_invalid_cli_override_raises_config_error(self) -> None:
        with pytest.raises(ConfigError, match="Invalid resolved configuration"):
            resolve_profile(AppConfig(), transport="carrier-pigeon")


class TestRedaction:
    def test_repr_never_contains_literal_secret_value(self) -> None:
        resolved = ResolvedProfile(user="alice", password="super-secret-value")  # noqa: S106
        text = repr(resolved)
        assert "super-secret-value" not in text
        assert "alice" not in text
        assert "literal, 18 chars" in text  # password
        assert "literal, 5 chars" in text  # user

    def test_repr_shows_unresolved_ssm_path_not_value(self) -> None:
        resolved = ResolvedProfile(password=SsmRef(ssm="/clickhouse/v1/pilot/tool/password"))
        text = repr(resolved)
        assert "unresolved, ssm:/clickhouse/v1/pilot/tool/password" in text

    def test_model_dump_redacts_secret_fields(self) -> None:
        resolved = ResolvedProfile(user="alice", password="super-secret-value")  # noqa: S106
        dumped = resolved.model_dump()
        assert dumped["user"] == "(literal, 5 chars)"
        assert dumped["password"] == "(literal, 18 chars)"  # noqa: S105
        assert "alice" not in str(dumped)
        assert "super-secret-value" not in str(dumped)

    def test_none_secret_fields_render_as_none(self) -> None:
        resolved = ResolvedProfile()
        text = repr(resolved)
        assert "user=None" in text
        assert "password=None" in text
