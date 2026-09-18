"""Tests for structlog configuration and stderr routing."""

import io
import logging
import sys

import pytest
import structlog

from clickhouse_tool.core.logging import get_logger, setup_logging

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_structlog():
    yield
    structlog.reset_defaults()


def test_configured_logging_writes_to_stderr_not_stdout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Verify that logging configuration sends output to stderr.
    fake_stdout = io.StringIO()
    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    setup_logging()
    logger = get_logger("test")
    logger.info("hello")

    assert fake_stdout.getvalue() == ""
    assert "hello" in fake_stderr.getvalue()


def test_verbose_flag_raises_level_to_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    setup_logging(verbose=True)
    logger = get_logger("test")
    logger.debug("debug-level message")

    assert "debug-level message" in fake_stderr.getvalue()


def test_non_verbose_suppresses_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    # Verify that debug messages do not appear in non-verbose mode.
    fake_stderr = io.StringIO()
    monkeypatch.setattr(sys, "stderr", fake_stderr)

    setup_logging(verbose=False)
    logger = get_logger("test")
    logger.debug("should not appear")

    assert "should not appear" not in fake_stderr.getvalue()


def test_stdlib_logging_untouched_by_structlog_setup() -> None:
    # setup_logging configures structlog only, not stdlib root logger.
    root = logging.getLogger()
    setup_logging()
    for handler in root.handlers:
        stream = getattr(handler, "stream", None)
        assert stream is not sys.stdout
