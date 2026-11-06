"""Tests for the one-line layout's cell renderers."""

# cspell:ignore ouncer qrstuvwxyz

from __future__ import annotations

from datetime import date

import pytest

from clickhouse_tool.formatters.cells import (
    cut,
    escape_message,
    host_cell,
    marker_cell,
    service_cell,
    severity_cell,
    shorten,
    source_cell,
    time_cell,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("number", "glyph", "letter"),
    [
        (1, "\U0001f52c", "T"),
        (4, "\U0001f52c", "T"),
        (5, "\U0001f41b", "D"),
        (8, "\U0001f41b", "D"),
        (9, "ℹ", "I"),  # noqa: RUF001
        (12, "ℹ", "I"),  # noqa: RUF001
        (13, "\U0001f514", "W"),
        (16, "\U0001f514", "W"),
        (17, "\U0001f525", "E"),
        (20, "\U0001f525", "E"),
        (21, "\U0001f4a5\U0001f4a5", "F"),
        (24, "\U0001f4a5\U0001f4a5", "F"),
    ],
)
def test_severity_ranges_map_to_glyph_and_letter(number: int, glyph: str, letter: str) -> None:
    assert glyph in severity_cell(number, terminal=True, glyphs=True)
    assert severity_cell(number, terminal=False, glyphs=True) == letter


@pytest.mark.parametrize("number", [0, 25, -1, None])
def test_unset_or_out_of_range_severity_is_blank_on_a_terminal_and_dash_piped(
    number: int | None,
) -> None:
    assert severity_cell(number, terminal=True, glyphs=True) == ""
    assert severity_cell(number, terminal=False, glyphs=True) == "-"


def test_info_glyph_is_dimmed_on_a_terminal() -> None:
    assert severity_cell(9, terminal=True, glyphs=True) == "\x1b[2mℹ\x1b[22m"  # noqa: RUF001


def test_no_glyphs_prints_words() -> None:
    assert [severity_cell(n, terminal=True, glyphs=False) for n in (1, 5, 9, 13, 17, 21)] == [
        "TRACE",
        "DEBUG",
        "INFO",
        "WARN",
        "ERROR",
        "FATAL",
    ]


def test_marker_cell() -> None:
    assert marker_cell(None, terminal=True) == ""
    assert marker_cell(237, terminal=True) == "\U0001f422"
    assert marker_cell(-18000, terminal=True) == "\U0001f52e"
    assert marker_cell(237, terminal=False) == ">"
    assert marker_cell(-18000, terminal=False) == "<"


def test_time_cell_is_short_only_for_today() -> None:
    today = date(2026, 11, 6)
    assert time_cell("2026-11-06 14:03:07", today=today, short=True) == "14:03:07"
    assert time_cell("2026-11-05 23:59:59", today=today, short=True) == "2026-11-05 23:59:59"
    assert time_cell("2026-11-06 14:03:07", today=today, short=False) == "2026-11-06 14:03:07"


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("clickhouse-1.example.com", "clickhouse-1"),
        ("10.0.12.7", "10.0.12.7"),
        ("fd00::1:2", "fd00::1:2"),
        ("192.0.2.10", "192.0.2.10"),
        ("gk3-kube-v0-nap-aj8bs4r8-d217e80c-ngd7", "gk3-..7e80c-ngd7"),
        ("2001:db8:85a3::8a2e:370:7334", "2001..e:370:7334"),
        ("", ""),
    ],
)
def test_host_cell(host: str, expected: str) -> None:
    assert host_cell(host, 16) == expected
    assert len(host_cell(host, 16)) <= 16


def test_service_cell_drops_the_unit_suffix_and_cuts_the_tail() -> None:
    assert service_cell("otelcol-contrib.service", 18) == "otelcol-contrib"
    assert (
        service_cell("snap.amazon-ssm-agent.amazon-ssm-agent.service", 18) == "snap.amazon-ssm-.."
    )
    assert len(service_cell("a" * 25, 18)) == 18


@pytest.mark.parametrize(
    ("namespace", "log_source", "container", "expected"),
    [
        ("ingress-nginx", "docker", "x", "ingress-nginx"),
        ("", "docker", "sentry-self-hosted-pgbouncer-1", "sent..ouncer-1"),
        ("", "docker", "", "docker"),
        ("", "winlog:Microsoft-Windows-Sysmon/Operational", "", "Sysmon"),
        ("", "winlog:Security", "", "Security"),
        ("", "winlog:Windows PowerShell", "", "Wind..werShell"),
        ("", "journald", "", "journald"),
        ("", "", "", ""),
    ],
)
def test_source_cell(namespace: str, log_source: str, container: str, expected: str) -> None:
    assert source_cell(namespace, log_source, container, 14) == expected


def test_shorten_and_cut_measure_cells_not_characters() -> None:
    assert shorten("abcdefghijklmnopqrstuvwxyz", 16, head=4) == "abcd..qrstuvwxyz"
    assert cut("x" * 20, 10) == "xxxxxxxx.."
    assert cut("\U0001f422" * 10, 10) == "\U0001f422" * 4 + ".."


def test_escape_message_controls_and_newlines() -> None:
    assert escape_message("a\x1b[31mb\rc", wrap=False) == "a\\x1b[31mb\\x0dc"
    assert escape_message("one\n\n\ntwo\r\nthree", wrap=False) == "one two three"
    assert escape_message("one\ntwo", wrap=True) == "one\ntwo"
    assert escape_message("tab\there", wrap=False) == "tab\there"
