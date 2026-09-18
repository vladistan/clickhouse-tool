"""Cross-backend equivalence: both adapters feed the single code table.

A second table anywhere is a defect. Parametrized over every row of
``core.errors._CODE_TABLE``: both backends translate a given server
code to the identical exception.
"""

from __future__ import annotations

import pytest

from clickhouse_tool.core.client.http import translate_http_error
from clickhouse_tool.core.client.native import translate_native_error
from clickhouse_tool.core.errors import _CODE_TABLE

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("code,expected_type", sorted(_CODE_TABLE.items()))
def test_native_and_http_agree_on_every_coded_error(code, expected_type) -> None:
    from clickhouse_driver.errors import ServerException

    native_exc = ServerException("DB::Exception: boom (version 1.0)", code=code)
    native_result = translate_native_error(native_exc)
    assert isinstance(native_result, expected_type)
    assert native_result.exit_code == expected_type.exit_code

    from clickhouse_connect.driver.exceptions import DatabaseError

    http_exc = DatabaseError("boom", code=code)
    http_result = translate_http_error(http_exc)
    assert isinstance(http_result, expected_type)
    assert http_result.exit_code == expected_type.exit_code

    assert native_result.exit_code == http_result.exit_code


def test_native_recovers_code_from_message_prefix_when_attribute_absent() -> None:
    from clickhouse_tool.core.errors import SchemaError

    exc = RuntimeError("Code: 60. DB::Exception: Table default.missing doesn't exist")
    result = translate_native_error(exc)
    assert isinstance(result, SchemaError)


def test_http_recovers_code_from_message_prefix_when_attribute_absent() -> None:
    from clickhouse_tool.core.errors import SchemaError

    exc = RuntimeError("(UNKNOWN_TABLE) Code: 60. DB::Exception: Table default.missing doesn't exist")
    result = translate_http_error(exc)
    assert isinstance(result, SchemaError)


def test_unmapped_code_produces_server_error_on_both_backends() -> None:
    from clickhouse_connect.driver.exceptions import DatabaseError
    from clickhouse_driver.errors import ServerException

    from clickhouse_tool.core.errors import ServerError

    native_result = translate_native_error(ServerException("weird", code=99999))
    http_result = translate_http_error(DatabaseError("weird", code=99999))
    assert isinstance(native_result, ServerError)
    assert isinstance(http_result, ServerError)


def test_write_refusal_is_code_classified_not_sql_parsed() -> None:
    """CH code 164/497 (permission denied) is how a readonly refusal surfaces --
    never by the client inspecting whether the statement looked like a write."""
    from clickhouse_driver.errors import ServerException

    from clickhouse_tool.core.errors import PermissionDenied

    exc = ServerException("Cannot execute query in readonly mode", code=164)
    result = translate_native_error(exc)
    assert isinstance(result, PermissionDenied)


def test_no_error_message_can_contain_a_credential_value() -> None:
    """The adapters must never fabricate message text -- they preserve the
    original message verbatim and add nothing that could carry a secret."""
    from clickhouse_driver.errors import ServerException

    secret = "s3cr3t-password"  # noqa: S105 - test fixture value, never a real credential
    exc = ServerException("Code: 193. Authentication failed", code=193)
    result = translate_native_error(exc)
    assert secret not in str(result)
    assert secret not in result.message
