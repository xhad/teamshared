"""Minimal SMTP mailer for console sign-in OTP delivery.

Stdlib ``smtplib`` only — no extra dependency. Sending is blocking, so callers
await :func:`send_login_code`, which offloads the SMTP round-trip to a thread
executor (same pattern the codebase uses for other sync I/O). Delivery is
best-effort from the caller's perspective: failures raise and the console logs
them without leaking which emails exist.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from teamshared.config import Settings
from teamshared.logging import get_logger

log = get_logger(__name__)


def smtp_configured(settings: Settings) -> bool:
    """True when enough SMTP settings are present to attempt delivery."""
    return bool(getattr(settings, "smtp_host", None) and getattr(settings, "smtp_from", None))


def _build_message(settings: Settings, to_email: str, code: str, ttl: int) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "Your teamshared sign-in code"
    msg["From"] = settings.smtp_from or ""
    msg["To"] = to_email
    msg.set_content(
        f"Your teamshared one-time sign-in code is:\n\n"
        f"    {code}\n\n"
        f"It expires in {ttl} seconds and can be used once.\n"
        f"If you didn't try to sign in, you can ignore this email.\n"
    )
    return msg


def _send_sync(settings: Settings, to_email: str, code: str, ttl: int) -> None:
    msg = _build_message(settings, to_email, code, ttl)
    host = settings.smtp_host or ""
    with smtplib.SMTP(host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


async def send_login_code(settings: Settings, to_email: str, code: str, ttl: int) -> None:
    """Email a one-time sign-in code. Raises on SMTP failure."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _send_sync, settings, to_email, code, ttl)
