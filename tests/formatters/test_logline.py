"""Tests for the one-line log layout formatter."""

# cspell:ignore kubelet ouncer

from __future__ import annotations

import re
from datetime import datetime

import pytest
from rich.cells import cell_len

from clickhouse_tool.core.config import LayoutWidths
from clickhouse_tool.core.models import ColumnMeta, RowSet
from clickhouse_tool.formatters.logline import SEPARATOR, LayoutOptions, LogLineFormatter

pytestmark = pytest.mark.unit

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_COLUMNS = ("ts", "level", "host", "service", "msg", "lag_s", "__sev", "__ns", "__src", "__ctr")


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _rows(*rows: tuple[object, ...]) -> RowSet:
    return RowSet(
        columns=tuple(ColumnMeta(name=c, ch_type="") for c in _COLUMNS),
        rows=tuple(rows),
        row_count=len(rows),
    )


def _row(
    msg: str = "hello",
    *,
    ts: str | None = None,
    host: str = "fw1.example.com",
    service: str = "dhcpd.service",
    lag: int | None = None,
    sev: int = 9,
    ns: str = "",
    src: str = "syslog",
    ctr: str = "",
) -> tuple[object, ...]:
    return (ts or f"{_today()} 14:03:07", "INFO", host, service, msg, lag, sev, ns, src, ctr)


def _render(rows: RowSet, **overrides: object) -> list[str]:
    settings: dict[str, object] = {
        "terminal": True,
        "follow": True,
        "tz": "UTC",
        "terminal_width": 120,
    }
    settings.update(overrides)
    options = LayoutOptions(**settings)  # type: ignore[arg-type]
    return [_ANSI.sub("", line) for line in LogLineFormatter(options).format(rows)]


def test_terminal_follow_line_shape_and_separator_column() -> None:
    (line,) = _render(_rows(_row()))
    prefix, message = line.split(SEPARATOR)
    assert message == "hello"
    assert cell_len(prefix) == 2 + 1 + 8 + 1 + 4 + 1 + 16 + 1 + 14 + 1 + 18
    assert "14:03:07" in prefix
    assert "fw1 " in prefix
    assert "dhcpd " in prefix
    assert "syslog" in prefix


def test_non_follow_terminal_uses_the_full_date() -> None:
    (line,) = _render(_rows(_row()), follow=False)
    assert line.startswith(f"   {_today()} 14:03:07 ")
    prefix = line.split(SEPARATOR)[0]
    assert cell_len(prefix) == 2 + 1 + 19 + 1 + 4 + 1 + 16 + 1 + 14 + 1 + 18


def test_a_row_from_another_day_shows_the_full_date_under_follow() -> None:
    (line,) = _render(_rows(_row(ts="2001-01-01 00:00:01")))
    assert "2001-01-01 00:00:01" in line


def test_full_timestamps_flag_forces_the_date() -> None:
    (line,) = _render(_rows(_row()), full_timestamps=True)
    assert _today() in line


def test_lines_never_exceed_the_terminal_width() -> None:
    lines = _render(_rows(_row("x" * 500), _row("short")))
    assert all(cell_len(line) <= 120 for line in lines)
    assert lines[0].endswith("..")
    assert lines[1].endswith("short")


def test_piped_output_is_ascii_full_dates_and_untruncated() -> None:
    (line,) = _render(_rows(_row("y" * 300, lag=400, sev=17)), terminal=False)
    assert line.startswith(f"> {_today()} 14:03:07 E ")
    assert line.endswith("y" * 300)
    assert "\U0001f422" not in line


def test_markers_and_glyphs_on_a_terminal() -> None:
    late, future, normal = _render(_rows(_row(lag=300, sev=13), _row(lag=-100, sev=21), _row()))
    assert late.startswith("\U0001f422 ") and "\U0001f514" in late
    assert future.startswith("\U0001f52e ") and "\U0001f4a5\U0001f4a5" in future
    assert normal.startswith("   14:03:07")


def test_no_glyphs_uses_words_and_a_five_cell_column() -> None:
    (line,) = _render(_rows(_row(sev=17)), glyphs=False)
    assert " ERROR " in line
    prefix = line.split(SEPARATOR)[0]
    assert cell_len(prefix) == 2 + 1 + 8 + 1 + 5 + 1 + 16 + 1 + 14 + 1 + 18


def test_empty_cells_show_a_dash() -> None:
    (line,) = _render(_rows(_row(host="", service="", src="")))
    cells = line.split(SEPARATOR)[0].split()
    assert cells[2:5] == ["-", "-", "-"]


def test_multi_line_message_is_one_line_unless_wrapping() -> None:
    (line,) = _render(_rows(_row("one\n\ntwo\r\nthree")))
    assert line.endswith("one two three")
    lines = _render(_rows(_row("one\ntwo")), wrap=True)
    assert len(lines) == 2
    assert lines[0].endswith("one")
    assert lines[1].strip() == "two"
    assert lines[1].index("two") == lines[0].index("one")


def test_control_characters_cannot_reach_the_terminal() -> None:
    (line,) = _render(_rows(_row("a\x1b[2Jb\x07")))
    assert "\x1b[2J" not in line
    assert "\\x1b[2Jb\\x07" in line


def test_bracketed_text_prints_verbatim() -> None:
    (line,) = _render(_rows(_row("mount [/var/lib/kubelet   /] failed")))
    assert "mount [/var/lib/kubelet   /] failed" in line


def test_width_override_moves_the_separator() -> None:
    (narrow,) = _render(_rows(_row()))
    (wide,) = _render(_rows(_row()), widths=LayoutWidths(host=24))
    assert wide.index(SEPARATOR) == narrow.index(SEPARATOR) + 8


@pytest.mark.parametrize(
    ("width", "cells_present"),
    [(120, 6), (90, 5), (70, 4), (50, 3)],
    ids=["all", "no-service", "no-source", "no-host"],
)
def test_narrow_terminals_drop_columns_right_to_left(width: int, cells_present: int) -> None:
    (line,) = _render(_rows(_row(lag=300)), terminal_width=width)
    prefix = line.split(SEPARATOR)[0]
    assert len(prefix.split()) == cells_present
    assert cell_len(line) <= width


def test_source_prefers_namespace_then_container_then_log_source() -> None:
    lines = _render(
        _rows(
            _row(ns="ingress-nginx", src="docker", ctr="c1"),
            _row(src="docker", ctr="sentry-self-hosted-pgbouncer-1"),
            _row(src="winlog:Microsoft-Windows-Sysmon/Operational"),
        )
    )
    assert "ingress-nginx" in lines[0]
    assert "sent..ouncer-1" in lines[1]
    assert "Sysmon" in lines[2]
