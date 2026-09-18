"""Tests for package metadata and basic imports."""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


def test_import_succeeds() -> None:
    import clickhouse_tool  # noqa: F401


def test_version_readable_from_about() -> None:
    from clickhouse_tool import __about__

    assert __about__.__version__ == "0.1.0"


def test_module_runs_without_traceback() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "clickhouse_tool", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
