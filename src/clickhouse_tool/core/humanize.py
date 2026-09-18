"""Human-friendly rendering for the table formatter: relative times and scaled numbers."""

from __future__ import annotations

from datetime import UTC, datetime

# Largest to smallest; seconds is the finest granularity, never sub-second.
_UNITS: tuple[tuple[str, int], ...] = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
_SECONDARY_THRESHOLD = 10


def format_relative_time(when: datetime, *, now: datetime | None = None) -> str:
    """Render `when` as e.g. ``2h 20m ago``.

    A second unit shows only at 10 or above (``1h ago``, not ``1h 3m ago``).
    """
    reference = now if now is not None else datetime.now(UTC)
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    elapsed = max(0, int((reference - when).total_seconds()))

    for index, (unit, size) in enumerate(_UNITS):
        if elapsed < size and unit != "s":
            continue
        primary = f"{elapsed // size}{unit}"
        if index + 1 < len(_UNITS):
            next_unit, next_size = _UNITS[index + 1]
            secondary_value = (elapsed % size) // next_size
            if secondary_value >= _SECONDARY_THRESHOLD:
                return f"{primary} {secondary_value}{next_unit} ago"
        return f"{primary} ago"
    return "0s ago"  # pragma: no cover -- the seconds branch always matches first


_NUMBER_SUFFIXES: tuple[tuple[float, str], ...] = ((1_000_000_000, "g"), (1_000_000, "m"), (1_000, "k"))


def humanize_number(value: float, *, decimals: int = 2) -> str:
    """Render a number with a k/m/g suffix, rounded to ``decimals`` places.

    A suffix only applies once the scaled value reaches 10, so 1024
    stays ``1024`` but 10000 becomes ``10k``.
    """
    magnitude = abs(value)
    for scale, suffix in _NUMBER_SUFFIXES:
        scaled = magnitude / scale
        if scaled >= 10:
            rounded = round(scaled, decimals)
            sign = "-" if value < 0 and rounded != 0 else ""
            return f"{sign}{_trim(rounded)}{suffix}"
    rounded = round(magnitude, decimals)
    sign = "-" if value < 0 and rounded != 0 else ""
    return f"{sign}{_trim(rounded)}"


def _trim(value: float) -> str:
    text = f"{value:.10f}".rstrip("0").rstrip(".")
    return text if text else "0"
