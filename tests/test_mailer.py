"""Unit tests for the console OTP SMTP mailer.

A fake ``smtplib.SMTP`` captures the round-trip so we can assert the message
content and the STARTTLS/login sequence without a real mail server.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import ClassVar

from teamshared.server import mailer


def _settings(**over: object) -> SimpleNamespace:
    base = dict(
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_username=None,
        smtp_password=None,
        smtp_from="teamshared <no-reply@test>",
        smtp_starttls=True,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_smtp_configured_requires_host_and_from() -> None:
    assert mailer.smtp_configured(_settings()) is True
    assert mailer.smtp_configured(_settings(smtp_host=None)) is False
    assert mailer.smtp_configured(_settings(smtp_from=None)) is False


def test_build_message_includes_code_and_ttl() -> None:
    msg = mailer._build_message(_settings(), "owner@acme.ai", "123456", 30)
    assert msg["To"] == "owner@acme.ai"
    assert msg["From"] == "teamshared <no-reply@test>"
    body = msg.get_content()
    assert "123456" in body
    assert "30 seconds" in body


class _FakeSMTP:
    instances: ClassVar[list[_FakeSMTP]] = []

    def __init__(self, host: str, port: int, timeout: int = 10) -> None:
        self.host = host
        self.port = port
        self.started_tls = False
        self.logged_in: tuple[str, str] | None = None
        self.sent: object = None
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def starttls(self) -> None:
        self.started_tls = True

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def send_message(self, msg: object) -> None:
        self.sent = msg


def test_send_login_code_uses_starttls_and_login(monkeypatch) -> None:
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    settings = _settings(smtp_username="u", smtp_password="p")
    asyncio.run(mailer.send_login_code(settings, "owner@acme.ai", "654321", 30))
    assert len(_FakeSMTP.instances) == 1
    smtp = _FakeSMTP.instances[0]
    assert smtp.host == "smtp.test"
    assert smtp.started_tls is True
    assert smtp.logged_in == ("u", "p")
    assert smtp.sent is not None


def test_send_login_code_skips_login_without_credentials(monkeypatch) -> None:
    _FakeSMTP.instances.clear()
    monkeypatch.setattr(mailer.smtplib, "SMTP", _FakeSMTP)
    asyncio.run(mailer.send_login_code(_settings(), "owner@acme.ai", "111111", 30))
    assert _FakeSMTP.instances[0].logged_in is None
