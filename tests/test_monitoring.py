"""Tests for Sentry monitoring setup."""

from unittest.mock import MagicMock

import pytest

from clickhouse_tool.core.monitoring import _DEFAULT_DSN, _DSN_ENV_VAR, setup_sentry

pytestmark = pytest.mark.unit


def test_setup_sentry_uses_env_override_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_DSN_ENV_VAR, "https://abc123@o0.ingest.us.sentry.io/1")
    mock_init = MagicMock()
    monkeypatch.setattr("clickhouse_tool.core.monitoring.sentry_sdk.init", mock_init)

    setup_sentry(environment="test")

    mock_init.assert_called_once()
    assert mock_init.call_args.kwargs["dsn"] == "https://abc123@o0.ingest.us.sentry.io/1"


def test_setup_sentry_defaults_to_real_dsn_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_DSN_ENV_VAR, raising=False)
    mock_init = MagicMock()
    monkeypatch.setattr("clickhouse_tool.core.monitoring.sentry_sdk.init", mock_init)

    setup_sentry(environment="test")

    mock_init.assert_called_once()
    assert mock_init.call_args.kwargs["dsn"] == _DEFAULT_DSN


def test_setup_sentry_is_noop_when_env_var_explicitly_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_DSN_ENV_VAR, "")
    mock_init = MagicMock()
    monkeypatch.setattr("clickhouse_tool.core.monitoring.sentry_sdk.init", mock_init)

    setup_sentry(environment="test")

    mock_init.assert_not_called()
