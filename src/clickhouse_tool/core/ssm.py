"""Lazy AWS SSM secret resolution.

Only connecting verbs call :func:`materialise_secrets`; ``config``
never does. Resolution is atomic: one failure discards this pass's
fetched values and raises, naming every failed field.
"""

from __future__ import annotations

from pydantic import SecretStr

from clickhouse_tool.core.config import ResolvedProfile, SsmRef
from clickhouse_tool.core.errors import ConfigError

_SECRET_FIELDS = ("user", "password")


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
    client = _ssm_client()

    for field_name, ref in pending.items():
        try:
            resolved_values[field_name] = _fetch(client, ref)
        except Exception as exc:  # funneled into one typed ConfigError below
            failures.append(f"{field_name} (ssm:{ref.ssm}): {exc}")

    if failures:
        msg = "Failed to resolve secret(s) from SSM: " + "; ".join(failures)
        raise ConfigError(msg)

    updates: dict[str, object] = {}
    for field_name, raw_value in resolved_values.items():
        updates[field_name] = SecretStr(raw_value) if field_name == "password" else raw_value

    return profile.model_copy(update=updates)


def _ssm_client() -> object:
    import boto3  # type: ignore[import-untyped]

    return boto3.client("ssm")


def _fetch(client: object, ref: SsmRef) -> str:
    """Fetch and decrypt one SSM parameter, honoring per-ref profile/region overrides."""
    target = client
    if ref.aws_profile is not None or ref.region is not None:
        import boto3

        session_kwargs: dict[str, str] = {}
        if ref.aws_profile is not None:
            session_kwargs["profile_name"] = ref.aws_profile
        session = boto3.Session(**session_kwargs)
        client_kwargs: dict[str, str] = {}
        if ref.region is not None:
            client_kwargs["region_name"] = ref.region
        target = session.client("ssm", **client_kwargs)

    response = target.get_parameter(Name=ref.ssm, WithDecryption=True)  # type: ignore[attr-defined]
    return str(response["Parameter"]["Value"])
