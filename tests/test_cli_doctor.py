from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

from typer.testing import CliRunner

from teamshared import cli


class _Response:
    def __init__(self, body: dict[str, Any]) -> None:
        self.body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self.body


class _HttpClient:
    body: ClassVar[dict[str, Any]] = {}

    def __init__(self, **_: Any) -> None:
        pass

    async def __aenter__(self) -> _HttpClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, _: str) -> _Response:
        return _Response(self.body)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        public_url="https://teamshared.test",
        host="127.0.0.1",
        port=8077,
    )


def test_doctor_reports_healthy_http_server(monkeypatch) -> None:
    _HttpClient.body = {
        "status": "ok",
        "components": {
            "server": "ok",
            "postgres": "ok",
            "semantic": "ok (local)",
            "graph": "disabled",
        },
    }
    monkeypatch.setattr(cli, "get_settings", _settings)
    monkeypatch.setattr(cli.httpx, "AsyncClient", _HttpClient)

    result = CliRunner().invoke(cli.app, ["doctor"])

    assert result.exit_code == 0
    assert "teamshared.test" in result.stdout
    assert "authenticated MCP" in result.stdout


def test_doctor_fails_on_degraded_component(monkeypatch) -> None:
    _HttpClient.body = {
        "status": "degraded",
        "components": {"postgres": "down"},
    }
    monkeypatch.setattr(cli, "get_settings", _settings)
    monkeypatch.setattr(cli.httpx, "AsyncClient", _HttpClient)

    result = CliRunner().invoke(cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "postgres" in result.stdout


def test_doctor_write_smoke_requires_token() -> None:
    result = CliRunner().invoke(cli.app, ["doctor", "--write-smoke"])

    assert result.exit_code == 2
    assert result.exception is not None
