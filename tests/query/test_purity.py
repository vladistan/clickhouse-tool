"""Import-purity gate for the query package.

Extended below to the whole package: every module in ``clickhouse_tool``
must import cleanly with neither driver installed at module scope --
only the client constructors import them, lazily.
"""

import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit

_FORBIDDEN_MODULES = ("clickhouse_driver", "clickhouse_connect", "boto3", "httpx")


def test_query_package_pulls_in_no_io_module_transitively() -> None:
    probe = (
        "import clickhouse_tool.query.builder, clickhouse_tool.query.intents, "
        "clickhouse_tool.query.columns, clickhouse_tool.query.timerange, "
        "clickhouse_tool.query.predicates, clickhouse_tool.query.sort, "
        "clickhouse_tool.query.tables, sys; "
        f"print([m for m in {_FORBIDDEN_MODULES!r} if m in sys.modules])"
    )
    # probe is built entirely from this module's own constants, never from
    # external input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


def test_whole_package_pulls_in_no_io_module_at_import_time() -> None:
    """Every module imports cleanly with neither backend driver present.
    Extends the query-only check above to the full package, including
    cli/ and core/client/."""
    probe = (
        "import pkgutil, sys, clickhouse_tool; "
        "[__import__(m.name) for m in pkgutil.walk_packages("
        "clickhouse_tool.__path__, clickhouse_tool.__name__ + '.')]; "
        f"print([m for m in {_FORBIDDEN_MODULES!r} if m in sys.modules])"
    )
    # probe is built entirely from this module's own constants, never from
    # external input.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]", result.stderr
