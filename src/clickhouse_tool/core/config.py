"""TOML config with five-level precedence merge and per-field provenance.

Precedence (high to low): CLI flag > env var > profile > config files > defaults.
Secret fields defer to :mod:`clickhouse_tool.core.ssm` for dereferencing.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, SecretStr, model_validator

from clickhouse_tool.core.errors import ConfigError

USER_CONFIG_PATH = Path.home() / ".config" / "clickhouse-tool" / "config.toml"
PROJECT_CONFIG_PATH = Path("clickhouse-tool.toml")

_ENV_PREFIX = "CLICKHOUSE_TOOL_"

_DEFAULTS: dict[str, Any] = {
    "host": "localhost",
    "port": 9000,
    "transport": "native",
    "database": "default",
    "secure": False,
    "logs_table": "otel_logs",
    "connect_timeout": 10,
    "query_timeout": 60,
}

# Fields resolvable from a CLI flag or env var, mapped to their ResolvedProfile name.
_OVERRIDABLE_FIELDS = (
    "host",
    "port",
    "transport",
    "database",
    "secure",
    "logs_table",
    "connect_timeout",
    "query_timeout",
    "user",
    "password",
)


AWS_DEFAULT_CHAIN = "boto3 default chain"

# (field, env vars in priority order)
_AWS_ENV: dict[str, tuple[str, ...]] = {
    "aws_profile": ("AWS_PROFILE",),
    "aws_region": ("AWS_REGION", "AWS_DEFAULT_REGION"),
}


class SsmRef(BaseModel):
    """A pointer at an AWS SSM parameter, in place of a literal secret value."""

    model_config = ConfigDict(frozen=True)

    ssm: str
    aws_profile: str | None = None
    region: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_aws_region_alias(cls, data: Any) -> Any:
        if isinstance(data, dict) and "aws_region" in data:
            data = dict(data)
            data.setdefault("region", data.pop("aws_region"))
        return data


def _coerce_secret(value: Any) -> Any:
    if isinstance(value, dict):
        return SsmRef(**value)
    return value


Secret = Annotated[str | SsmRef, BeforeValidator(_coerce_secret)]


class Profile(BaseModel):
    """One named connection profile as it appears in the TOML file."""

    model_config = ConfigDict(frozen=True)

    host: str = _DEFAULTS["host"]
    port: int = _DEFAULTS["port"]
    transport: Literal["native", "http"] = _DEFAULTS["transport"]
    database: str = _DEFAULTS["database"]
    user: Secret | None = None
    password: Secret | None = None
    secure: bool = _DEFAULTS["secure"]
    logs_table: str = _DEFAULTS["logs_table"]
    connect_timeout: int = _DEFAULTS["connect_timeout"]
    query_timeout: int = _DEFAULTS["query_timeout"]
    aws_profile: str | None = None
    aws_region: str | None = None


class LayoutWidths(BaseModel):
    """Column widths, in terminal cells, for the one-line log layout."""

    model_config = ConfigDict(frozen=True)

    host: int = 16
    source: int = 14
    service: int = 18


class LayoutConfig(BaseModel):
    """``[layout]`` section of the TOML config."""

    model_config = ConfigDict(frozen=True)

    widths: LayoutWidths = LayoutWidths()


class AppConfig(BaseModel):
    """The fully-parsed contents of one or more merged TOML files."""

    model_config = ConfigDict(frozen=True)

    default_profile: str | None = None
    default_format: str = "toon"
    default_window: str = "2h"
    default_timezone: str = "local"
    sentry_dsn: str | None = None
    aws_profile: str | None = None
    aws_region: str | None = None
    late_after_s: int = 124
    future_after_s: int = 5
    layout: LayoutConfig = LayoutConfig()
    profiles: dict[str, Profile] = {}


class ResolvedProfile(BaseModel):
    """The merged, per-field-provenanced configuration for one run.

    ``user``/``password`` may still hold an unresolved :class:`SsmRef` --
    call :func:`clickhouse_tool.core.ssm.materialise_secrets` before
    connecting. ``config`` never does.
    """

    host: str = _DEFAULTS["host"]
    port: int = _DEFAULTS["port"]
    transport: Literal["native", "http"] = _DEFAULTS["transport"]
    database: str = _DEFAULTS["database"]
    user: Secret | None = None
    password: Secret | SecretStr | None = None
    secure: bool = _DEFAULTS["secure"]
    logs_table: str = _DEFAULTS["logs_table"]
    connect_timeout: int = _DEFAULTS["connect_timeout"]
    query_timeout: int = _DEFAULTS["query_timeout"]
    default_format: str = "toon"
    default_window: str = "2h"
    default_timezone: str = "local"
    late_after_s: int = 124
    future_after_s: int = 5
    layout: LayoutConfig = LayoutConfig()
    aws_profile: str | None = None
    aws_region: str | None = None
    active_profile: str | None = None
    sources: dict[str, str] = {}

    def __repr__(self) -> str:
        return self._redacted_repr()

    def _redacted_repr(self) -> str:
        fields = ", ".join(
            f"{name}={self._redact_field(name)!r}" for name in self.__class__.model_fields
        )
        return f"{self.__class__.__name__}({fields})"

    def _redact_field(self, name: str) -> Any:
        if name not in ("user", "password"):
            return getattr(self, name)
        value = getattr(self, name)
        return _describe_secret(value)

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        dumped = super().model_dump(*args, **kwargs)
        for name in ("user", "password"):
            if name in dumped:
                dumped[name] = _describe_secret(getattr(self, name))
        return dumped


def _describe_secret(value: Any) -> str | None:
    """Render a secret-typed field for display -- never the value itself."""
    if value is None:
        return None
    if isinstance(value, SsmRef):
        return f"(unresolved, ssm:{value.ssm})"
    if isinstance(value, SecretStr):
        return f"(ssm-resolved, {len(value.get_secret_value())} chars)"
    if isinstance(value, str):
        return f"(literal, {len(value)} chars)"
    return "(redacted)"


def load_layers(
    project_path: Path | None = None,
    user_path: Path | None = None,
) -> AppConfig:
    """Load and merge the project-local and user-level TOML files.

    Project-local overrides user-level, field by field, before either
    reaches :func:`resolve_profile`. Missing files are not an error --
    an absent file contributes nothing.
    """
    user_path = user_path if user_path is not None else USER_CONFIG_PATH
    project_path = project_path if project_path is not None else PROJECT_CONFIG_PATH

    merged: dict[str, Any] = {}
    for path in (user_path, project_path):
        merged = _merge_file(merged, path)

    try:
        return AppConfig.model_validate(merged)
    except Exception as exc:
        msg = f"Invalid configuration: {exc}"
        raise ConfigError(msg) from exc


def _merge_file(base: dict[str, Any], path: Path) -> dict[str, Any]:
    if not path.exists():
        return base
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Malformed TOML in {path}: {exc}"
        raise ConfigError(msg) from exc

    merged = dict(base)
    profiles = dict(merged.get("profiles", {}))
    incoming_profiles = data.pop("profiles", {})
    for name, fields in incoming_profiles.items():
        profiles[name] = {**profiles.get(name, {}), **fields}
    merged.update(data)
    if profiles:
        merged["profiles"] = profiles
    return merged


def resolve_profile(
    config: AppConfig,
    profile_name: str | None = None,
    **cli_overrides: Any,
) -> ResolvedProfile:
    """Merge defaults, the selected profile, environment, and CLI overrides.

    SSM references are left unresolved -- this function never touches
    AWS. Raises :class:`ConfigError` for an unknown profile, naming every
    profile that is available.
    """
    sources: dict[str, str] = {}
    resolved: dict[str, Any] = dict(_DEFAULTS)
    resolved["default_format"] = config.default_format
    resolved["default_window"] = config.default_window
    resolved["default_timezone"] = config.default_timezone
    resolved["late_after_s"] = config.late_after_s
    resolved["future_after_s"] = config.future_after_s
    resolved["layout"] = config.layout
    for key in resolved:
        sources[key] = "default"

    effective_profile = profile_name or config.default_profile
    if effective_profile is not None:
        if effective_profile not in config.profiles:
            available = ", ".join(sorted(config.profiles)) or "none"
            msg = f"Unknown profile: '{effective_profile}'. Available profiles: {available}"
            raise ConfigError(msg)
        profile = config.profiles[effective_profile]
        for field_name in profile.model_fields_set:
            resolved[field_name] = getattr(profile, field_name)
            sources[field_name] = f"profile: {effective_profile}"

    for field_name in _OVERRIDABLE_FIELDS:
        env_var = f"{_ENV_PREFIX}{field_name.upper()}"
        raw_value = os.environ.get(env_var)
        if raw_value is None:
            continue
        resolved[field_name] = _coerce_env_value(field_name, raw_value)
        sources[field_name] = f"env: {env_var}"

    for field_name in _OVERRIDABLE_FIELDS:
        value = cli_overrides.get(field_name)
        if value is not None:
            resolved[field_name] = value
            sources[field_name] = f"cli: --{field_name}"

    for key in _AWS_ENV:
        resolved[key], sources[key] = resolve_aws_setting(key, config, effective_profile)

    resolved["active_profile"] = effective_profile
    resolved["sources"] = sources
    try:
        return ResolvedProfile(**resolved)
    except Exception as exc:
        msg = f"Invalid resolved configuration: {exc}"
        raise ConfigError(msg) from exc


def resolve_aws_setting(
    key: str, config: AppConfig, profile_name: str | None
) -> tuple[str | None, str]:
    """Pick ``aws_profile`` or ``aws_region``: env, then profile, then top level.

    Returns the value and the level that supplied it. A value on the SSM
    reference itself outranks all of these (see ``core.ssm``).
    """
    for env_var in _AWS_ENV[key]:
        env_value = os.environ.get(env_var)
        if env_value:
            return env_value, f"env: {env_var}"
    if profile_name is not None:
        profile_value = getattr(config.profiles[profile_name], key)
        if profile_value is not None:
            return profile_value, f"profile: {profile_name}"
    top_value = getattr(config, key)
    if top_value is not None:
        return top_value, "config"
    return None, AWS_DEFAULT_CHAIN


def _coerce_env_value(field_name: str, raw_value: str) -> Any:
    if field_name in ("port", "connect_timeout", "query_timeout"):
        try:
            return int(raw_value)
        except ValueError:
            msg = f"Invalid {_ENV_PREFIX}{field_name.upper()} value: '{raw_value}'. Must be an integer"
            raise ConfigError(msg) from None
    if field_name == "secure":
        return raw_value.strip().lower() in ("1", "true", "yes", "on")
    return raw_value
