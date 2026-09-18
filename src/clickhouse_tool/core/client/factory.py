"""Backend selection: dispatches on ``profile.transport``.

No cross-backend fallback -- failover doubles every timeout and hides
the actual point of failure. A failure names its backend, host, port,
then stops.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clickhouse_tool.core.client.base import ChClient
from clickhouse_tool.core.client.http import HttpChClient
from clickhouse_tool.core.client.native import NativeChClient
from clickhouse_tool.core.errors import ConfigError


@runtime_checkable
class ClientProfile(Protocol):
    """The subset of a resolved profile the client factory needs.

    Structural, not a concrete import of ``ResolvedProfile`` -- the
    client layer stays free of a config import. Any object with these
    attributes satisfies this Protocol.
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


def make_client(profile: ClientProfile) -> ChClient:
    """Construct the ``ChClient`` named by ``profile.transport``.

    Raises :class:`ConfigError` for an unset or unrecognised transport,
    before it opens any socket.
    """
    if profile.transport == "native":
        return NativeChClient(
            host=profile.host,
            port=profile.port,
            database=profile.database,
            user=profile.user,
            password=profile.password,
            secure=profile.secure,
            connect_timeout=profile.connect_timeout,
            query_timeout=profile.query_timeout,
        )
    if profile.transport == "http":
        return HttpChClient(
            host=profile.host,
            port=profile.port,
            database=profile.database,
            user=profile.user,
            password=profile.password,
            secure=profile.secure,
            connect_timeout=profile.connect_timeout,
            query_timeout=profile.query_timeout,
        )
    raise ConfigError(f"unrecognised transport {profile.transport!r}: expected 'native' or 'http'")
