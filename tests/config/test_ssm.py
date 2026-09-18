"""Tests for lazy, atomic-on-partial-failure SSM secret materialisation."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from clickhouse_tool.core.config import ResolvedProfile, SsmRef
from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.ssm import materialise_secrets

pytestmark = pytest.mark.unit


class _FakeSsmClient:
    def __init__(self, values: dict[str, str], failures: dict[str, Exception] | None = None):
        self._values = values
        self._failures = failures or {}

    def get_parameter(self, Name: str, WithDecryption: bool) -> dict[str, Any]:  # noqa: N803
        if Name in self._failures:
            raise self._failures[Name]
        return {"Parameter": {"Value": self._values[Name]}}


def test_no_ssm_refs_returns_profile_unchanged() -> None:
    profile = ResolvedProfile(user="alice", password="literal-pw")  # noqa: S106
    result = materialise_secrets(profile)
    assert result is profile


def test_resolves_single_ssm_field() -> None:
    profile = ResolvedProfile(password=SsmRef(ssm="/a/password"))
    fake = _FakeSsmClient({"/a/password": "hunter2"})
    with patch("clickhouse_tool.core.ssm._ssm_client", return_value=fake):
        result = materialise_secrets(profile)
    assert isinstance(result.password, SecretStr)
    assert result.password.get_secret_value() == "hunter2"


def test_resolved_password_repr_shows_ssm_resolved_not_value() -> None:
    profile = ResolvedProfile(password=SsmRef(ssm="/a/password"))
    fake = _FakeSsmClient({"/a/password": "hunter2"})
    with patch("clickhouse_tool.core.ssm._ssm_client", return_value=fake):
        result = materialise_secrets(profile)
    text = repr(result)
    assert "hunter2" not in text
    assert "ssm-resolved, 7 chars" in text


def test_per_ref_profile_and_region_override_client_construction() -> None:
    profile = ResolvedProfile(password=SsmRef(ssm="/a/password", aws_profile="other", region="us-west-2"))
    fake = _FakeSsmClient({"/a/password": "hunter2"})

    fake_session = type(
        "FakeSession",
        (),
        {"client": lambda self, service, **kw: fake},
    )()

    with (
        patch("clickhouse_tool.core.ssm._ssm_client", return_value=_FakeSsmClient({})),
        patch("boto3.Session", return_value=fake_session),
    ):
        result = materialise_secrets(profile)
    assert result.password.get_secret_value() == "hunter2"  # type: ignore[union-attr]


def test_resolves_user_as_plain_string_not_secretstr() -> None:
    profile = ResolvedProfile(user=SsmRef(ssm="/a/user"))
    fake = _FakeSsmClient({"/a/user": "svc-account"})
    with patch("clickhouse_tool.core.ssm._ssm_client", return_value=fake):
        result = materialise_secrets(profile)
    assert result.user == "svc-account"
    assert not isinstance(result.user, SecretStr)


def test_resolves_multiple_fields() -> None:
    profile = ResolvedProfile(user=SsmRef(ssm="/a/user"), password=SsmRef(ssm="/a/password"))
    fake = _FakeSsmClient({"/a/user": "svc", "/a/password": "hunter2"})
    with patch("clickhouse_tool.core.ssm._ssm_client", return_value=fake):
        result = materialise_secrets(profile)
    assert result.user == "svc"
    assert result.password.get_secret_value() == "hunter2"  # type: ignore[union-attr]


def test_partial_failure_fails_whole_pass_atomically() -> None:
    profile = ResolvedProfile(user=SsmRef(ssm="/a/user"), password=SsmRef(ssm="/a/password"))
    fake = _FakeSsmClient(
        {"/a/user": "svc"},
        failures={"/a/password": RuntimeError("AccessDeniedException")},
    )
    with (
        patch("clickhouse_tool.core.ssm._ssm_client", return_value=fake),
        pytest.raises(ConfigError) as exc_info,
    ):
        materialise_secrets(profile)

    message = str(exc_info.value)
    assert "/a/password" in message
    assert "AccessDeniedException" in message


def test_partial_failure_never_leaks_a_successfully_fetched_value() -> None:
    profile = ResolvedProfile(user=SsmRef(ssm="/a/user"), password=SsmRef(ssm="/a/password"))
    fake = _FakeSsmClient(
        {"/a/user": "should-not-appear-anywhere"},
        failures={"/a/password": RuntimeError("boom")},
    )
    with (
        patch("clickhouse_tool.core.ssm._ssm_client", return_value=fake),
        pytest.raises(ConfigError) as exc_info,
    ):
        materialise_secrets(profile)
    assert "should-not-appear-anywhere" not in str(exc_info.value)


def test_error_names_every_failed_field_when_multiple() -> None:
    profile = ResolvedProfile(user=SsmRef(ssm="/a/user"), password=SsmRef(ssm="/a/password"))
    fake = _FakeSsmClient(
        {},
        failures={
            "/a/user": RuntimeError("user fail"),
            "/a/password": RuntimeError("password fail"),
        },
    )
    with (
        patch("clickhouse_tool.core.ssm._ssm_client", return_value=fake),
        pytest.raises(ConfigError) as exc_info,
    ):
        materialise_secrets(profile)
    message = str(exc_info.value)
    assert "user" in message
    assert "password" in message


def test_config_command_never_triggers_ssm(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `config` command must be able to describe a profile with unresolved
    SSM refs without ever importing boto3 or opening a network connection --
    it simply never calls materialise_secrets."""
    profile = ResolvedProfile(password=SsmRef(ssm="/a/password"))
    # Not calling materialise_secrets at all is the contract; assert the
    # profile is fully usable for display purposes without it.
    assert isinstance(profile.password, SsmRef)
    text = repr(profile)
    assert "unresolved, ssm:/a/password" in text
