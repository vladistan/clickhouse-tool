"""Tests for package metadata and basic imports."""

import importlib.metadata
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_import_succeeds() -> None:
    import clickhouse_tool  # noqa: F401


def test_about_version_matches_installed_metadata() -> None:
    from clickhouse_tool import __about__

    assert __about__.__version__ == importlib.metadata.version("clickhouse-tool")


def test_pyproject_takes_its_version_from_about() -> None:
    pyproject = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text())

    assert "version" not in pyproject["project"]
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["hatch"]["version"]["path"] == "src/clickhouse_tool/__about__.py"


def test_module_runs_without_traceback() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "clickhouse_tool", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr
