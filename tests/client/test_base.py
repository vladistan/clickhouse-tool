"""Tests for ChClient protocol and contract."""

import subprocess
import sys

import pytest

from clickhouse_tool.core.client.base import ChClient
from clickhouse_tool.core.models import RowSet, SqlStatement

pytestmark = pytest.mark.unit


def test_fake_client_satisfies_chclient_protocol(fake_client) -> None:
    assert isinstance(fake_client, ChClient)


def test_fake_client_ping_execute_stream_close(fake_client) -> None:
    stmt = SqlStatement(sql="SELECT 1")
    fake_client.ping()
    rowset = fake_client.execute(stmt)
    assert isinstance(rowset, RowSet)
    rows = list(fake_client.stream(stmt))
    assert rows == []
    fake_client.close()
    assert fake_client.closed is True


def test_no_driver_imported_by_the_contract_layer() -> None:
    # A fresh process: whatever other tests in this session already
    # imported (a real backend client, exercised elsewhere in this suite)
    # must not affect this check.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import clickhouse_tool.core.client.base; "
            "assert 'clickhouse_driver' not in sys.modules; "
            "assert 'clickhouse_connect' not in sys.modules",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
