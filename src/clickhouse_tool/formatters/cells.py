"""Cell renderers for the one-line log layout.

Each function turns one raw value into its column text. Glyphs on a
terminal, ASCII when piped; widths are terminal cells, not characters.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import date

from rich.cells import cell_len

ELLIPSIS = ".."
DIM_ON = "\x1b[2m"
DIM_OFF = "\x1b[22m"

# (lowest SeverityNumber, name, terminal glyph, piped letter)
SEVERITIES: tuple[tuple[int, str, str, str], ...] = (
    (1, "TRACE", "\U0001f52c", "T"),
    (5, "DEBUG", "\U0001f41b", "D"),
    (9, "INFO", "ℹ", "I"),  # noqa: RUF001 -- the glyph is the point
    (13, "WARN", "\U0001f514", "W"),
    (17, "ERROR", "\U0001f525", "E"),
    (21, "FATAL", "\U0001f4a5\U0001f4a5", "F"),
)
LATE_GLYPH, FUTURE_GLYPH = "\U0001f422", "\U0001f52e"
LATE_ASCII, FUTURE_ASCII = ">", "<"
_WINLOG_PREFIX = "winlog:"
_WINLOG_NOISE = ("Microsoft-Windows-", "/Operational")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_NEWLINES = re.compile(r"(?:\r?\n)+")  # a lone CR is a control character, escaped


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def visible_len(text: str) -> int:
    """Width in terminal cells, ignoring ANSI style sequences."""
    return cell_len(_ANSI.sub("", text))


def pad(text: str, width: int) -> str:
    """Right-pad ``text`` to ``width`` cells; a wider text is returned as is."""
    return text + " " * max(0, width - visible_len(text))


def cut(text: str, width: int) -> str:
    """Keep the head of ``text`` and end with ``..`` when it exceeds ``width`` cells."""
    if cell_len(text) <= width:
        return text
    keep = width - len(ELLIPSIS)
    out = ""
    for char in text:
        if cell_len(out + char) > keep:
            break
        out += char
    return out + ELLIPSIS


def shorten(text: str, width: int, head: int) -> str:
    """``head`` characters, ``..``, then the tail that fills ``width`` cells."""
    if cell_len(text) <= width:
        return text
    tail = width - head - len(ELLIPSIS)
    return f"{text[:head]}{ELLIPSIS}{text[-tail:]}" if tail > 0 else cut(text, width)


def dim(text: str, terminal: bool) -> str:
    return f"{DIM_ON}{text}{DIM_OFF}" if terminal else text


def severity_cell(number: int | None, *, terminal: bool, glyphs: bool) -> str:
    """Glyph, letter or word for a ``SeverityNumber``; blank (or ``-`` piped) when unset."""
    level = _severity_level(number)
    if level is None:
        return "" if terminal else "-"
    _, name, glyph, letter = level
    if not terminal:
        return letter
    if not glyphs:
        return name
    return dim(glyph, terminal) if name == "INFO" else glyph


def _severity_level(number: int | None) -> tuple[int, str, str, str] | None:
    if number is None or not 1 <= number <= 24:
        return None
    for level in reversed(SEVERITIES):
        if number >= level[0]:
            return level
    return None


def marker_cell(lag_s: int | None, *, terminal: bool) -> str:
    """Late or future-stamped marker from a flagged lag; blank otherwise."""
    if lag_s is None:
        return ""
    if lag_s > 0:
        return LATE_GLYPH if terminal else LATE_ASCII
    return FUTURE_GLYPH if terminal else FUTURE_ASCII


def time_cell(ts: str, *, today: date, short: bool) -> str:
    """``HH:MM:SS`` when ``short`` and the row is from ``today``; else the full form."""
    if short and ts[:10] == today.isoformat():
        return ts[11:19]
    return ts


def host_cell(host: str, width: int) -> str:
    """Domain dropped at the first dot; IP addresses kept whole; head..tail over ``width``."""
    if not host:
        return ""
    if not _is_ip(host):
        host = host.split(".", 1)[0]
    return shorten(host, width, head=4)


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def service_cell(service: str, width: int) -> str:
    """``.service`` suffix dropped; head then ``..`` over ``width``."""
    service = service.removesuffix(".service")
    return cut(service, width)


def source_cell(namespace: str, log_source: str, container: str, width: int) -> str:
    """Namespace, else container for docker, else a Windows channel, else the log source."""
    if namespace:
        text = namespace
    elif log_source == "docker" and container:
        text = container
    elif log_source.startswith(_WINLOG_PREFIX):
        text = log_source.removeprefix(_WINLOG_PREFIX)
        for noise in _WINLOG_NOISE:
            text = text.replace(noise, "")
    else:
        text = log_source
    return shorten(text, width, head=4)


def escape_message(text: str, *, wrap: bool) -> str:
    """Control characters as ``\\xNN``; newline runs become one space unless wrapping."""
    if not wrap:
        text = _NEWLINES.sub(" ", text)
    return _CONTROL.sub(lambda m: f"\\x{ord(m.group()):02x}", text)
