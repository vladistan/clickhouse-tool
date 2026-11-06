"""Tests for Sentry monitoring setup."""

# cspell:ignore ssecret

import gzip
import http.server
import json
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import sentry_sdk

from clickhouse_tool.__about__ import __version__
from clickhouse_tool.cli import main
from clickhouse_tool.cli.commands.config import config as config_command
from clickhouse_tool.core.errors import ConfigError, ConnectionFailed
from clickhouse_tool.core.monitoring import (
    _DEFAULT_DSN,
    _DSN_ENV_VAR,
    detect_environment,
    environment_for,
    mask_dsn,
    resolve_dsn,
    scrub_argv,
    setup_sentry,
)

pytestmark = pytest.mark.unit

_ENV_DSN = "https://abc123@o0.ingest.us.sentry.io/1"
_USER_DSN = "https://userkey@o0.ingest.us.sentry.io/2"
_PROJECT_DSN = "https://projectkey@o0.ingest.us.sentry.io/3"


@pytest.fixture(autouse=True)
def config_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Point both config layers at empty temp paths and clear the env override."""
    paths = {"user": tmp_path / "user.toml", "project": tmp_path / "project.toml"}
    monkeypatch.setattr("clickhouse_tool.core.config.USER_CONFIG_PATH", paths["user"])
    monkeypatch.setattr("clickhouse_tool.core.config.PROJECT_CONFIG_PATH", paths["project"])
    monkeypatch.delenv(_DSN_ENV_VAR, raising=False)
    return paths


def test_setup_sentry_uses_env_override_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_DSN_ENV_VAR, _ENV_DSN)
    mock_init = MagicMock()
    monkeypatch.setattr("clickhouse_tool.core.monitoring.sentry_sdk.init", mock_init)

    setup_sentry(environment="test")

    mock_init.assert_called_once()
    assert mock_init.call_args.kwargs["dsn"] == _ENV_DSN


def test_setup_sentry_defaults_to_real_dsn_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_init = MagicMock()
    monkeypatch.setattr("clickhouse_tool.core.monitoring.sentry_sdk.init", mock_init)

    setup_sentry(environment="test")

    mock_init.assert_called_once()
    assert mock_init.call_args.kwargs["dsn"] == _DEFAULT_DSN


def test_setup_sentry_is_noop_when_env_var_explicitly_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_DSN_ENV_VAR, "")
    mock_init = MagicMock()
    monkeypatch.setattr("clickhouse_tool.core.monitoring.sentry_sdk.init", mock_init)

    setup_sentry(environment="test")

    mock_init.assert_not_called()


def test_setup_sentry_is_noop_when_config_file_dsn_is_empty(
    monkeypatch: pytest.MonkeyPatch, config_files: dict[str, Path]
) -> None:
    config_files["user"].write_text('sentry_dsn = ""\n')
    mock_init = MagicMock()
    monkeypatch.setattr("clickhouse_tool.core.monitoring.sentry_sdk.init", mock_init)

    setup_sentry(environment="test")

    mock_init.assert_not_called()


def test_resolve_dsn_falls_back_to_built_in_default() -> None:
    assert resolve_dsn() == (_DEFAULT_DSN, "default")


def test_resolve_dsn_reads_user_config_file(config_files: dict[str, Path]) -> None:
    config_files["user"].write_text(f'sentry_dsn = "{_USER_DSN}"\n')

    assert resolve_dsn() == (_USER_DSN, "config file")


def test_resolve_dsn_project_config_overrides_user_config(config_files: dict[str, Path]) -> None:
    config_files["user"].write_text(f'sentry_dsn = "{_USER_DSN}"\n')
    config_files["project"].write_text(f'sentry_dsn = "{_PROJECT_DSN}"\n')

    assert resolve_dsn() == (_PROJECT_DSN, "config file")


def test_resolve_dsn_env_overrides_config_file(
    monkeypatch: pytest.MonkeyPatch, config_files: dict[str, Path]
) -> None:
    config_files["user"].write_text(f'sentry_dsn = "{_USER_DSN}"\n')
    monkeypatch.setenv(_DSN_ENV_VAR, _ENV_DSN)

    assert resolve_dsn() == (_ENV_DSN, f"env: {_DSN_ENV_VAR}")


def test_resolve_dsn_uses_default_when_config_file_is_malformed(
    config_files: dict[str, Path],
) -> None:
    config_files["user"].write_text("not [ valid toml")

    assert resolve_dsn() == (_DEFAULT_DSN, "default")


def test_resolve_dsn_uses_default_when_config_shape_is_invalid(
    config_files: dict[str, Path],
) -> None:
    config_files["user"].write_text('[profiles.pilot]\nport = "not-an-int"\n')

    assert resolve_dsn() == (_DEFAULT_DSN, "default")


def test_mask_dsn_hides_the_key() -> None:
    assert mask_dsn(_ENV_DSN) == "https://***@o0.ingest.us.sentry.io/1"


def test_mask_dsn_names_the_disabled_state() -> None:
    assert mask_dsn("") == "(disabled)"


def test_config_command_shows_masked_dsn_and_its_source(
    config_files: dict[str, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    config_files["user"].write_text(f'sentry_dsn = "{_USER_DSN}"\n')

    config_command(profile=None)

    shown = json.loads(capsys.readouterr().out)
    assert shown["sentry_dsn"] == "https://***@o0.ingest.us.sentry.io/2"
    assert shown["sources"]["sentry_dsn"] == "config file"
    assert "userkey" not in json.dumps(shown)


class _EnvelopeSink(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.headers.get("content-encoding") == "gzip":
            body = gzip.decompress(body)
        self.server.envelopes.append(body.decode())  # type: ignore[attr-defined]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args: object) -> None:
        pass


@pytest.fixture
def sentry_server(monkeypatch: pytest.MonkeyPatch) -> Iterator[http.server.HTTPServer]:
    """A local HTTP server standing in for Sentry; the tool's DSN points at it."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _EnvelopeSink)
    server.envelopes = []  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv(_DSN_ENV_VAR, f"http://key@127.0.0.1:{server.server_port}/1")
    yield server
    client = sentry_sdk.get_client()
    if client.is_active():
        client.close()
    for scope in (
        sentry_sdk.get_global_scope(),
        sentry_sdk.get_isolation_scope(),
        sentry_sdk.get_current_scope(),
    ):
        scope.set_client(None)
    server.shutdown()
    server.server_close()


def _events(server: http.server.HTTPServer) -> list[dict[str, Any]]:
    """Every ``event`` item across the envelopes the server received."""
    events = []
    for envelope in server.envelopes:  # type: ignore[attr-defined]
        lines = envelope.splitlines()[1:]
        for header, payload in zip(lines[::2], lines[1::2], strict=False):
            if json.loads(header).get("type") == "event":
                events.append(json.loads(payload))
    return events


def _run_cli(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], failing_with: Exception | None = None
) -> int:
    monkeypatch.setattr(sys, "argv", ["clickhouse-tool", *argv])
    if failing_with is not None:

        def explode(*_args: object, **_kwargs: object) -> None:
            raise failing_with

        monkeypatch.setattr(main.logs, "wiring", MagicMock(load_profile=explode))
    with pytest.raises(SystemExit) as exit_info:
        main.run()
    sentry_sdk.flush(timeout=2)
    return int(exit_info.value.code or 0)


def test_unexpected_crash_sends_exactly_one_event(
    monkeypatch: pytest.MonkeyPatch, sentry_server: http.server.HTTPServer
) -> None:
    code = _run_cli(monkeypatch, ["logs"], failing_with=RuntimeError("boom"))

    events = _events(sentry_server)
    assert code == 1
    assert len(events) == 1
    assert events[0]["exception"]["values"][-1]["type"] == "RuntimeError"
    assert events[0]["release"] == __version__


@pytest.mark.parametrize(
    "error",
    [ConfigError("bad config"), ConnectionFailed("no route")],
    ids=["config-error", "connection-failed"],
)
def test_typed_errors_send_nothing(
    monkeypatch: pytest.MonkeyPatch, sentry_server: http.server.HTTPServer, error: Exception
) -> None:
    _run_cli(monkeypatch, ["logs"], failing_with=error)

    assert _events(sentry_server) == []


def test_usage_error_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, sentry_server: http.server.HTTPServer
) -> None:
    code = _run_cli(monkeypatch, ["logs", "--no-such-flag"])

    assert code == 2
    assert _events(sentry_server) == []


def test_crash_report_carries_no_argument_values(
    monkeypatch: pytest.MonkeyPatch, sentry_server: http.server.HTTPServer
) -> None:
    _run_cli(
        monkeypatch,
        ["logs", "-s", "topsecret", "--host=db1.internal"],
        failing_with=RuntimeError("boom"),
    )

    (event,) = _events(sentry_server)
    assert event["extra"]["sys.argv"] == ["logs", "-s", "--host"]
    body = json.dumps(event)
    assert "topsecret" not in body
    assert "db1.internal" not in body


def test_scrub_argv_keeps_commands_and_flag_names_only() -> None:
    commands = frozenset({"logs", "metrics", "values"})

    assert scrub_argv(["logs", "-s", "secret", "--host=db1", "SELECT 1"], commands) == [
        "logs",
        "-s",
        "--host",
    ]
    assert scrub_argv(["metrics", "values", "cpu", "-n5"], commands) == ["metrics", "values", "-n"]
    assert scrub_argv(["--profile", "pilot", "logs", "-ssecret"], commands) == [
        "--profile",
        "logs",
        "-s",
    ]


def test_crash_report_carries_no_local_variable_values(
    monkeypatch: pytest.MonkeyPatch, sentry_server: http.server.HTTPServer
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        search_term = "-".join(["local", "marker", "value"])  # noqa: F841
        raise RuntimeError("boom")

    monkeypatch.setattr(sys, "argv", ["clickhouse-tool", "logs"])
    monkeypatch.setattr(main.logs, "wiring", MagicMock(load_profile=explode))
    with pytest.raises(SystemExit):
        main.run()

    (event,) = _events(sentry_server)
    assert "local-marker-value" not in json.dumps(event)


def test_crash_with_unreachable_sentry_still_exits_promptly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_DSN_ENV_VAR, "http://key@127.0.0.1:9/1")
    monkeypatch.setattr(sys, "argv", ["clickhouse-tool", "logs"])
    monkeypatch.setattr(
        main.logs, "wiring", MagicMock(load_profile=MagicMock(side_effect=RuntimeError("boom")))
    )
    started = time.monotonic()

    with pytest.raises(SystemExit) as exit_info:
        main.run()

    assert exit_info.value.code == 1
    assert time.monotonic() - started < 4
    client = sentry_sdk.get_client()
    client.close(timeout=0)
    for scope in (
        sentry_sdk.get_global_scope(),
        sentry_sdk.get_isolation_scope(),
        sentry_sdk.get_current_scope(),
    ):
        scope.set_client(None)


@pytest.mark.parametrize(
    ("direct_url", "expected"),
    [
        ('{"url": "file:///src/clickhouse-tool", "dir_info": {"editable": true}}', "local"),
        ('{"url": "file:///src/clickhouse-tool", "dir_info": {}}', "local"),
        (None, "prod"),
        ('{"url": "https://example.org/x.whl", "archive_info": {}}', "prod"),
    ],
    ids=["editable", "local-directory", "index-install", "archive-url"],
)
def test_environment_for_install_metadata(direct_url: str | None, expected: str) -> None:
    assert environment_for(direct_url) == expected


def test_detect_environment_reads_a_real_dist_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dist_info = tmp_path / "clickhouse_tool-9.9.9.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: clickhouse-tool\nVersion: 9.9.9\n"
    )
    monkeypatch.setattr(sys, "path", [str(tmp_path)])

    assert detect_environment() == "prod"

    (dist_info / "direct_url.json").write_text(
        '{"url": "file:///x", "dir_info": {"editable": true}}'
    )
    assert detect_environment() == "local"


def test_detect_environment_is_local_without_an_installed_distribution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "path", [])

    assert detect_environment() == "local"


def test_force_crash_env_var_sends_one_event_and_exits_one(
    monkeypatch: pytest.MonkeyPatch, sentry_server: http.server.HTTPServer
) -> None:
    monkeypatch.setenv(main.FORCE_CRASH_ENV_VAR, "1")
    code = _run_cli(monkeypatch, ["config"])

    (event,) = _events(sentry_server)
    assert code == 1
    assert "forced crash" in json.dumps(event)
