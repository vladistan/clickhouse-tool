"""TOON hostile-content corpus.

Every case is run through the header-count invariant as well as an
exact-output assertion. This is what pushes toon.py's coverage bar to
95%, above the 90% bar for the other three formatters.
"""

import re

import pytest

from clickhouse_tool.formatters.toon import encode, render_field

pytestmark = pytest.mark.unit

_HEADER_RE = re.compile(r"^result\[(\d+)\]\{[^}]*\}:$")

# (label, raw field value, expected rendered field)
HOSTILE_CASES = [
    ("comma", "a,b", '"a,b"'),
    ("double_quote", 'say "hi"', '"say \\"hi\\""'),
    ("backslash", "C:\\path\\to", '"C:\\\\path\\\\to"'),
    ("newline", "line1\nline2", '"line1\\nline2"'),
    ("carriage_return", "line1\rline2", '"line1\\rline2"'),
    ("tab", "a\tb", '"a\\tb"'),
    ("leading_whitespace", " leading", '" leading"'),
    ("trailing_whitespace", "trailing ", '"trailing "'),
    ("empty_string", "", '""'),
    ("control_char_null", "a\x00b", "a\x00b"),
    ("control_char_bell", "a\x07b", "a\x07b"),
    ("emoji", "log 🔥 event", "log 🔥 event"),
    ("wide_char", "日本語ログ", "日本語ログ"),
    ("surrogate_pair_emoji", "👨‍👩‍👧‍👦 family", "👨‍👩‍👧‍👦 family"),
    ("comma_and_quote_together", 'a,"b"', '"a,\\"b\\""'),
    ("multi_line_body", "start\nmiddle line\nend", '"start\\nmiddle line\\nend"'),
]


@pytest.mark.parametrize("label,raw,expected", HOSTILE_CASES, ids=[c[0] for c in HOSTILE_CASES])
def test_hostile_field_exact_output(label, raw, expected):
    assert render_field(raw) == expected


@pytest.mark.parametrize("label,raw,expected", HOSTILE_CASES, ids=[c[0] for c in HOSTILE_CASES])
def test_hostile_field_round_trips_through_a_row_without_breaking_boundaries(
    make_rowset, label, raw, expected
):
    rows = make_rowset(["a", "b"], [(raw, "sentinel")])
    document = encode(rows)
    lines = document.splitlines()
    header_match = _HEADER_RE.match(lines[0])
    assert header_match is not None
    assert int(header_match.group(1)) == 1
    # Exactly one data row -- the hostile content did not fracture the row boundary.
    assert len(lines) == 2
    assert lines[1] == f"  {expected},sentinel"


def test_empty_string_and_null_are_distinguishable():
    assert render_field("") == '""'
    assert render_field(None) == "-"
    assert render_field("") != render_field(None)


def test_wide_lifted_row_with_many_map_keys_encodes_without_header_drift(make_rowset):
    columns = [f"col_{i}" for i in range(200)]
    values = tuple(f"v{i},{i}" for i in range(200))
    rows = make_rowset(columns, [values])
    document = encode(rows)
    lines = document.splitlines()
    header_match = _HEADER_RE.match(lines[0])
    assert header_match is not None
    assert int(header_match.group(1)) == 1
    assert len(lines) == 2
    assert lines[1].count('"') == 400  # every one of the 200 fields is quoted


def test_full_hostile_corpus_preserves_header_count_invariant(make_rowset):
    raws = [raw for _label, raw, _expected in HOSTILE_CASES]
    rows = make_rowset(["field"], [(raw,) for raw in raws])
    document = encode(rows)
    lines = document.splitlines()
    header_match = _HEADER_RE.match(lines[0])
    assert header_match is not None
    assert int(header_match.group(1)) == len(raws) == len(lines) - 1
