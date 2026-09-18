"""Tests for the typer application, global options, and the error funnel.

Invoke ``run()`` with ``sys.argv`` patched, not ``CliRunner`` -- that
always reports ``exit_code=1``, never the real one.
"""

from __future__ import annotations

import sys

import pytest
from typer.testing import CliRunner

from clickhouse_tool.cli.main import app
from clickhouse_tool.core.errors import ConfigError

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_help_exits_zero_and_lists_every_verb() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for verb in ("logs", "hosts", "services", "list", "lift", "query", "config"):
        assert verb in result.stdout


def test_single_letter_flag_is_accepted_as_host_not_help() -> None:
    result = runner.invoke(app, ["logs", "--help"])
    assert result.exit_code == 0
    assert "-h" in result.stdout
    assert "--host" in result.stdout


def test_each_verb_help_exits_zero() -> None:
    for verb in ("logs", "hosts", "services", "list", "lift", "query", "config"):
        result = runner.invoke(app, [verb, "--help"])
        assert result.exit_code == 0, result.stdout


def test_typed_error_prints_message_to_stderr_and_exits_with_its_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import clickhouse_tool.cli.commands.config as config_module
    import clickhouse_tool.cli.main as main_module

    def _boom(_profile: str | None, **_kwargs: object) -> None:
        raise ConfigError("bad profile")

    monkeypatch.setattr(config_module.wiring, "load_profile", _boom)
    monkeypatch.setattr(sys, "argv", ["clickhouse-tool", "config"])
    with pytest.raises(SystemExit) as exc_info:
        main_module.run()
    assert exc_info.value.code == 3
    assert "bad profile" in capsys.readouterr().err


def test_unknown_command_exits_2() -> None:
    result = runner.invoke(app, ["cluster-health"])
    assert result.exit_code == 2


def test_invalid_flag_combination_exits_3(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.main as main_module

    monkeypatch.setattr(
        sys, "argv", ["clickhouse-tool", "hosts", "--stream", "metrics", "--level", "error"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main_module.run()
    assert exc_info.value.code == 3


def test_keyboard_interrupt_exits_130(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.main as main_module

    def _raise_interrupt() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(main_module, "app", _raise_interrupt)
    with pytest.raises(SystemExit) as exc_info:
        main_module.run()
    assert exc_info.value.code == 130


def test_unexpected_error_exits_1_with_no_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    import clickhouse_tool.cli.main as main_module

    def _raise_value_error() -> None:
        raise ValueError("boom")

    monkeypatch.setattr(main_module, "app", _raise_value_error)
    with pytest.raises(SystemExit) as exc_info:
        main_module.run()
    assert exc_info.value.code == 1
