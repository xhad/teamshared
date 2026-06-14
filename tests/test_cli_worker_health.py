"""`teamshared worker-health <component>` Docker healthcheck command."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from typer.testing import CliRunner

import teamshared.memory.working as working_mod
from teamshared import cli

runner = CliRunner()


def _fake_working(beat: str | None) -> type:
    class _FakeWorking:
        def __init__(self, url: str, default_ttl: int, **_: object) -> None:
            self.url = url

        connect = AsyncMock()
        close = AsyncMock()
        last_heartbeat = AsyncMock(return_value=beat)

    return _FakeWorking


def test_worker_health_ok_when_heartbeat_present(monkeypatch) -> None:
    monkeypatch.setattr(
        cli, "get_settings",
        lambda: SimpleNamespace(redis_url="redis://x", session_ttl=60),
    )
    monkeypatch.setattr(
        working_mod, "WorkingMemory", _fake_working("2026-06-05T00:00:00Z")
    )
    result = runner.invoke(cli.app, ["worker-health", "distiller"])
    assert result.exit_code == 0
    assert "heartbeat ok" in result.stdout


def test_worker_health_fails_when_heartbeat_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        cli, "get_settings",
        lambda: SimpleNamespace(redis_url="redis://x", session_ttl=60),
    )
    monkeypatch.setattr(working_mod, "WorkingMemory", _fake_working(None))
    result = runner.invoke(cli.app, ["worker-health", "curator"])
    assert result.exit_code == 1
    assert "no recent heartbeat" in result.stdout
