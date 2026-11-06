"""Lazy AWS SSM secret resolution.

Only connecting verbs call :func:`materialise_secrets`; ``config``
never does. Resolution is atomic: one failure discards this pass's
fetched values and raises, naming every failed field.
"""

from __future__ import annotations

from typing import NamedTuple

from pydantic import SecretStr

from clickhouse_tool.core.config import AWS_DEFAULT_CHAIN, ResolvedProfile, SsmRef
from clickhouse_tool.core.errors import ConfigError

_SECRET_FIELDS = ("user", "password")
_HINT = (
    "Set aws_profile and aws_region on the SSM reference, the connection profile, "
    "or the config top level; AWS_PROFILE and AWS_REGION in the environment win "
    "over the config."
)


class AwsTarget(NamedTuple):
    """The AWS profile and region one SSM lookup uses, each with its source."""

    profile: str | None
    profile_source: str
    region: str | None
    region_source: str

    def describe(self) -> str:
        return (
            f"AWS profile {self.profile or AWS_DEFAULT_CHAIN} ({self.profile_source}), "
            f"region {self.region or AWS_DEFAULT_CHAIN} ({self.region_source})"
        )


def aws_target(profile: ResolvedProfile, ref: SsmRef) -> AwsTarget:
    """Combine the reference's own settings with the profile's resolved ones."""
    aws_profile: str | None = ref.aws_profile
    profile_source = "ssm reference"
    if aws_profile is None:
        aws_profile = profile.aws_profile
        profile_source = profile.sources.get("aws_profile", AWS_DEFAULT_CHAIN)
    region: str | None = ref.region
    region_source = "ssm reference"
    if region is None:
        region = profile.aws_region
        region_source = profile.sources.get("aws_region", AWS_DEFAULT_CHAIN)
    return AwsTarget(aws_profile, profile_source, region, region_source)


def materialise_secrets(profile: ResolvedProfile) -> ResolvedProfile:
    """Resolve every field on ``profile`` that is still an :class:`SsmRef`.

    A literal or :class:`SecretStr` stays untouched. ``password`` ends up
    a :class:`SecretStr`; ``user`` stays plain. Raises
    :class:`ConfigError` naming the failed fields.
    """
    pending: dict[str, SsmRef] = {}
    for field_name in _SECRET_FIELDS:
        value = getattr(profile, field_name)
        if isinstance(value, SsmRef):
            pending[field_name] = value

    if not pending:
        return profile

    resolved_values: dict[str, str] = {}
    failures: list[str] = []
    clients: dict[tuple[str | None, str | None], object] = {}

    for field_name, ref in pending.items():
        target = aws_target(profile, ref)
        try:
            key = (target.profile, target.region)
            if key not in clients:
                clients[key] = _ssm_client(target.profile, target.region)
            resolved_values[field_name] = _fetch(clients[key], ref)
        except Exception as exc:  # funneled into one typed ConfigError below
            failures.append(describe_ssm_failure(field_name, ref, target, exc))

    if failures:
        msg = "Failed to resolve secret(s) from SSM: " + "; ".join(failures) + f". {_HINT}"
        raise ConfigError(msg)

    updates: dict[str, object] = {}
    for field_name, raw_value in resolved_values.items():
        updates[field_name] = SecretStr(raw_value) if field_name == "password" else raw_value

    return profile.model_copy(update=updates)


def describe_ssm_failure(field_name: str, ref: SsmRef, target: AwsTarget, exc: Exception) -> str:
    """One failed field: parameter, AWS target with sources, and the AWS detail if any."""
    detail = str(exc).strip().rstrip(":").strip()
    text = f"{field_name} (ssm:{ref.ssm}) via {target.describe()}"
    return f"{text}: {detail}" if detail else text


def _ssm_client(aws_profile: str | None, aws_region: str | None) -> object:
    import boto3  # type: ignore[import-untyped]

    session = boto3.Session(profile_name=aws_profile)
    return session.client("ssm", region_name=aws_region)


def _fetch(client: object, ref: SsmRef) -> str:
    """Fetch and decrypt one SSM parameter."""
    response = client.get_parameter(Name=ref.ssm, WithDecryption=True)  # type: ignore[attr-defined]
    return str(response["Parameter"]["Value"])
