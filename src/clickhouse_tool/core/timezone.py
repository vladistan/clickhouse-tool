"""Resolves the display timezone for `logs`, honouring `--utc` and the profile.

ClickHouse's own `formatDateTime` does the conversion server-side, given
an IANA zone name -- this module only decides which name to pass it.
"""

from __future__ import annotations

import os

_LOCALTIME_PATH = "/etc/localtime"
_ZONEINFO_MARKER = "zoneinfo/"


def local_timezone_name() -> str:
    """The machine's IANA zone name, e.g. ``America/Los_Angeles``.

    Falls back to ``UTC`` wherever there is no ``/etc/localtime``
    symlink to read, as on Windows.
    """
    try:
        target = os.path.realpath(_LOCALTIME_PATH)
    except OSError:
        return "UTC"
    if _ZONEINFO_MARKER not in target:
        return "UTC"
    return target.split(_ZONEINFO_MARKER, 1)[1]


def resolve_display_timezone(*, utc: bool, configured: str) -> str:
    """Pick the IANA zone `logs` should render timestamps in.

    ``--utc`` always wins. Otherwise this uses the profile's
    ``default_timezone`` verbatim, except the literal ``"local"``,
    which resolves to the machine's own zone.
    """
    if utc:
        return "UTC"
    if configured == "local":
        return local_timezone_name()
    return configured
