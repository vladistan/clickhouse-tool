"""Tests for aws_profile / aws_region resolution and attributed SSM errors."""

from __future__ import annotations

import re
from typing import Any, ClassVar
from unittest.mock import patch

import pytest
from botocore.exceptions import ClientError, NoCredentialsError, NoRegionError, ProfileNotFound

from clickhouse_tool.core.config import (
    AWS_DEFAULT_CHAIN,
    AppConfig,
    Profile,
    SsmRef,
    load_layers,
    resolve_profile,
)
from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.ssm import materialise_secrets

pytestmark = pytest.mark.unit

_AWS_ENV = ("AWS_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION")


@pytest.fixture(autouse=True)
def _clean_aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AWS_ENV:
        monkeypatch.delenv(name, raising=False)


def _config(**top: Any) -> AppConfig:
    return AppConfig(
        profiles={"ars": Profile(host="h", aws_profile="from-profile", aws_region="eu-west-3")},
        **top,
    )


def test_env_beats_profile_beats_top_level(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config(aws_profile="from-top", aws_region="us-west-1")

    resolved = resolve_profile(config, "ars")
    assert (resolved.aws_profile, resolved.sources["aws_profile"]) == (
        "from-profile",
        "profile: ars",
    )
    assert (resolved.aws_region, resolved.sources["aws_region"]) == ("eu-west-3", "profile: ars")

    monkeypatch.setenv("AWS_PROFILE", "from-env")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    resolved = resolve_profile(config, "ars")
    assert (resolved.aws_profile, resolved.sources["aws_profile"]) == (
        "from-env",
        "env: AWS_PROFILE",
    )
    assert (resolved.aws_region, resolved.sources["aws_region"]) == (
        "ap-south-1",
        "env: AWS_DEFAULT_REGION",
    )

    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    assert resolve_profile(config, "ars").sources["aws_region"] == "env: AWS_REGION"


def test_top_level_applies_when_profile_sets_nothing() -> None:
    config = AppConfig(profiles={"p": Profile()}, aws_profile="from-top")

    resolved = resolve_profile(config, "p")

    assert (resolved.aws_profile, resolved.sources["aws_profile"]) == ("from-top", "config")
    assert (resolved.aws_region, resolved.sources["aws_region"]) == (None, AWS_DEFAULT_CHAIN)


def test_each_key_falls_back_independently(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "eu-central-1")
    config = AppConfig(profiles={"p": Profile(aws_profile="from-profile")})

    resolved = resolve_profile(config, "p")

    assert resolved.sources["aws_profile"] == "profile: p"
    assert resolved.sources["aws_region"] == "env: AWS_REGION"


def test_shipped_example_config_resolves_with_no_aws_settings_set(tmp_path: Any) -> None:
    config = load_layers(project_path=tmp_path / "none.toml", user_path=tmp_path / "none2.toml")
    resolved = resolve_profile(config)
    assert resolved.aws_profile is None
    assert resolved.sources["aws_profile"] == AWS_DEFAULT_CHAIN


@pytest.mark.parametrize("key", ["region", "aws_region"])
def test_ssm_reference_accepts_both_region_spellings(key: str) -> None:
    ref = SsmRef(**{"ssm": "/a", key: "eu-west-1"})
    assert ref.region == "eu-west-1"


class _FakeSsm:
    def __init__(self, values: dict[str, str] | None = None, raises: Exception | None = None):
        self._values = values or {}
        self._raises = raises

    def get_parameter(self, Name: str, WithDecryption: bool) -> dict[str, Any]:  # noqa: N803
        if self._raises is not None:
            raise self._raises
        return {"Parameter": {"Value": self._values[Name]}}


class _FakeSession:
    calls: ClassVar[list[tuple[str | None, str | None]]] = []

    def __init__(self, profile_name: str | None = None, fake: _FakeSsm | None = None) -> None:
        self._profile = profile_name
        self._fake = fake or _FakeSsm({"/a/password": "pw"})  # pragma: allowlist secret

    def client(self, service: str, region_name: str | None = None) -> _FakeSsm:
        _FakeSession.calls.append((self._profile, region_name))
        return self._fake


@pytest.mark.parametrize(
    ("ref", "profile_kwargs", "env", "expected"),
    [
        (
            SsmRef(ssm="/a/password", aws_profile="ref-p", region="ref-r"),
            {},
            {},
            ("ref-p", "ref-r"),
        ),
        (
            SsmRef(ssm="/a/password"),
            {},
            {"AWS_PROFILE": "env-p", "AWS_REGION": "env-r"},
            ("env-p", "env-r"),
        ),
        (
            SsmRef(ssm="/a/password"),
            {"aws_profile": "prof-p", "aws_region": "prof-r"},
            {},
            ("prof-p", "prof-r"),
        ),
        (SsmRef(ssm="/a/password"), {}, {}, (None, None)),
        (
            SsmRef(ssm="/a/password", aws_profile="ref-p"),
            {"aws_region": "prof-r"},
            {},
            ("ref-p", "prof-r"),
        ),
    ],
    ids=[
        "ssm-reference",
        "env",
        "profile",
        "default-chain",
        "reference-profile-plus-profile-region",
    ],
)
def test_session_is_built_from_the_winning_values(
    monkeypatch: pytest.MonkeyPatch,
    ref: SsmRef,
    profile_kwargs: dict[str, str],
    env: dict[str, str],
    expected: tuple[str | None, str | None],
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    config = AppConfig(profiles={"p": Profile(password=ref, **profile_kwargs)})
    resolved = resolve_profile(config, "p")
    _FakeSession.calls = []

    with patch("boto3.Session", _FakeSession):
        result = materialise_secrets(resolved)

    assert _FakeSession.calls == [expected]
    assert result.password.get_secret_value() == "pw"  # type: ignore[union-attr]


def _failing(error: Exception) -> type[_FakeSession]:
    class _Session(_FakeSession):
        def __init__(self, profile_name: str | None = None) -> None:
            super().__init__(profile_name, _FakeSsm(raises=error))

    return _Session


@pytest.mark.parametrize(
    "error",
    [
        ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "nope"}}, "GetParameter"
        ),
        ClientError({"Error": {"Code": "ParameterNotFound", "Message": ""}}, "GetParameter"),
        ProfileNotFound(profile="dev"),
        NoCredentialsError(),
        NoRegionError(),
    ],
    ids=[
        "access-denied",
        "not-found-empty-detail",
        "profile-not-found",
        "no-credentials",
        "no-region",
    ],
)
def test_failures_name_the_aws_target_with_sources(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setenv("AWS_PROFILE", "dev")
    config = AppConfig(
        profiles={"ars": Profile(password=SsmRef(ssm="/example/pw"), aws_region="eu-central-1")}
    )
    resolved = resolve_profile(config, "ars")

    with patch("boto3.Session", _failing(error)), pytest.raises(ConfigError) as info:
        materialise_secrets(resolved)

    message = str(info.value)
    assert "password (ssm:/example/pw)" in message
    assert "AWS profile dev (env: AWS_PROFILE)" in message
    assert "region eu-central-1 (profile: ars)" in message
    assert "aws_profile and aws_region" in message
    # an empty AWS detail must not leave "operation:" dangling before the hint
    assert re.search(r"operation:\s*[.;]", message) is None


def test_session_failure_is_reported_like_a_lookup_failure() -> None:
    config = AppConfig(profiles={"p": Profile(password=SsmRef(ssm="/a/pw"), aws_profile="ghost")})
    resolved = resolve_profile(config, "p")

    def _raise(profile_name: str | None = None) -> None:
        raise ProfileNotFound(profile=profile_name)

    with patch("boto3.Session", _raise), pytest.raises(ConfigError, match="AWS profile ghost"):
        materialise_secrets(resolved)
