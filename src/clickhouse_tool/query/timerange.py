"""Time-range window parser.

The count binds as a parameter. INTERVAL syntax needs a literal unit,
so the unit comes from this fixed accepted set. ClickHouse evaluates
`now()` server-side, so client clock skew never matters.
"""

from __future__ import annotations

import re

from clickhouse_tool.core.errors import ConfigError

_UNIT_TO_INTERVAL: dict[str, str] = {
    "s": "SECOND",
    "m": "MINUTE",
    "h": "HOUR",
    "d": "DAY",
    "w": "WEEK",
    "M": "MONTH",
}

_PATTERN = re.compile(r"^(\d+)([smhdwM])$")


def parse_time_range(window: str) -> tuple[int, str]:
    """Parse a compact window ('15m', '2w', ...) into (count, unit)."""
    match = _PATTERN.match(window)
    if match is None:
        accepted = ", ".join(sorted(_UNIT_TO_INTERVAL))
        raise ConfigError(
            f"unrecognised time range '{window}'; unit must be one of: {accepted}"
        )
    count = int(match.group(1))
    unit = _UNIT_TO_INTERVAL[match.group(2)]
    return count, unit


_UNIT_TO_SECONDS: dict[str, int] = {
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    "M": 2592000,
}


def window_seconds(window: str) -> int:
    """Approximate a window's length in seconds, for bucket-size heuristics."""
    match = _PATTERN.match(window)
    if match is None:
        accepted = ", ".join(sorted(_UNIT_TO_INTERVAL))
        raise ConfigError(
            f"unrecognised time range '{window}'; unit must be one of: {accepted}"
        )
    return int(match.group(1)) * _UNIT_TO_SECONDS[match.group(2)]


_BUCKET_CANDIDATES: tuple[tuple[int, str], ...] = (
    (1, "1s"), (5, "5s"), (10, "10s"), (15, "15s"), (30, "30s"),
    (60, "1m"), (300, "5m"), (600, "10m"), (900, "15m"), (1800, "30m"),
    (3600, "1h"), (7200, "2h"), (10800, "3h"), (21600, "6h"), (43200, "12h"),
    (86400, "1d"), (604800, "7d"),
)
_TARGET_BUCKET_COUNT = 36


_MINUTE_PRECISION_THRESHOLD_SECONDS = 3 * 3600


def default_time_precision(window: str) -> str:
    """``"s"`` (seconds) for windows under 3h, else ``"m"`` (minutes).

    A window spanning many hours doesn't need second-level timestamps
    in table output -- they add width without adding useful detail.
    """
    return "s" if window_seconds(window) < _MINUTE_PRECISION_THRESHOLD_SECONDS else "m"


def default_bucket_size(window: str) -> str:
    """A histogram bucket width sized so ``window`` yields roughly 36 buckets.

    Snaps up to the nearest "nice" duration from a fixed candidate list
    (1s..7d), rather than an arbitrary fraction of the window.
    """
    ideal = window_seconds(window) / _TARGET_BUCKET_COUNT
    for seconds, label in _BUCKET_CANDIDATES:
        if seconds >= ideal:
            return label
    return _BUCKET_CANDIDATES[-1][1]
