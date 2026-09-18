"""Turns a resolved profile into a client, and its logs table into a name.

Where a profile unwraps a secret or becomes a client. Table resolution
is a separate path (:func:`resolve_logs_table`), so the two never diverge.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from clickhouse_tool.core.client.base import ChClient
from clickhouse_tool.core.client.factory import make_client
from clickhouse_tool.core.config import ResolvedProfile, SsmRef, load_layers, resolve_profile
from clickhouse_tool.core.errors import ConfigError
from clickhouse_tool.core.ssm import materialise_secrets
from clickhouse_tool.query.tables import validate_qualified_table

_DRIVER_PACKAGE = {"native": "clickhouse-driver", "http": "clickhouse-connect"}


@dataclass(slots=True)
class ConnectionParams:
    """A resolved profile narrowed to the plain types the client protocol needs.

    Not frozen: ``ClientProfile`` declares settable attributes, and mypy's
    structural check on a ``Protocol`` requires a matching settable field.
    """

    host: str
    port: int
    transport: str
    database: str
    user: str
    password: str
    secure: bool
    connect_timeout: float
    query_timeout: float


def _unwrap_credential(value: str | SsmRef | SecretStr | None, field_name: str) -> str:
    if value is None:
        return ""
    if isinstance(value, SsmRef):
        raise ConfigError(
            f"unresolved secret reference on '{field_name}' (ssm:{value.ssm}) survived into "
            "the connection adapter"
        )
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return value


def open_client(resolved_profile: ResolvedProfile) -> ChClient:
    """Materialise secrets, narrow types into the adapter, and open the backend client."""
    profile = materialise_secrets(resolved_profile)
    params = ConnectionParams(
        host=profile.host,
        port=profile.port,
        transport=profile.transport,
        database=profile.database,
        user=_unwrap_credential(profile.user, "user"),
        password=_unwrap_credential(profile.password, "password"),
        secure=profile.secure,
        connect_timeout=float(profile.connect_timeout),
        query_timeout=float(profile.query_timeout),
    )
    try:
        return make_client(params)
    except ImportError as exc:
        package = _DRIVER_PACKAGE.get(profile.transport, profile.transport)
        raise ConfigError(
            f"transport '{profile.transport}' requires the '{package}' package, "
            f"which is not installed -- install it with `pip install clickhouse-tool[{profile.transport}]`"
        ) from exc


def resolve_logs_table(profile: ResolvedProfile) -> str:
    """Turn a resolved profile's database and logs table into a validated qualified name."""
    return validate_qualified_table(profile.database, profile.logs_table)


_METRICS_GAUGE_TABLE = "otel_metrics_gauge"


def resolve_metrics_table(profile: ResolvedProfile) -> str:
    """Turn a resolved profile's database into the metrics gauge table's qualified name."""
    return validate_qualified_table(profile.database, _METRICS_GAUGE_TABLE)


def load_profile(profile_name: str | None, **cli_overrides: object) -> ResolvedProfile:
    """Load the TOML config layers and resolve the profile for one CLI invocation."""
    config = load_layers()
    return resolve_profile(config, profile_name, **cli_overrides)
