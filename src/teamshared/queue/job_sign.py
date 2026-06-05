"""HMAC signing for distill/curate Redis queue jobs (Stage 4.1).

When ``TEAMSHARED_JOB_SIGNING_SECRET`` is set, producers wrap each job in a
versioned envelope ``{"v", "job", "sig"}`` so workers reject forged payloads.
Without a secret (local dev), jobs remain plain JSON dicts on the wire.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from enum import StrEnum
from typing import Any

SIGNATURE_VERSION = 1


class JobSignError(StrEnum):
    MALFORMED = "malformed"
    UNSIGNED = "unsigned"
    INVALID_SIGNATURE = "invalid_signature"
    VERSION_MISMATCH = "version_mismatch"


def _canonical_bytes(job: dict[str, Any]) -> bytes:
    return json.dumps(
        job, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def compute_signature(job: dict[str, Any], secret: str) -> str:
    """Return the hex HMAC-SHA256 signature for ``job``."""
    return hmac.new(
        secret.encode("utf-8"), _canonical_bytes(job), hashlib.sha256
    ).hexdigest()


def encode_job(job: dict[str, Any], secret: str | None) -> str:
    """Serialize a queue job. Signs when ``secret`` is set."""
    if not secret:
        return json.dumps(job, separators=(",", ":"))
    envelope = {
        "v": SIGNATURE_VERSION,
        "job": job,
        "sig": compute_signature(job, secret),
    }
    return json.dumps(envelope, separators=(",", ":"))


def decode_job(raw: str, secret: str | None) -> tuple[dict[str, Any] | None, JobSignError | None]:
    """Parse and optionally verify a queue payload.

    Returns ``(job, None)`` on success or ``(None, error)`` on failure.
    """
    try:
        parsed: Any = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, JobSignError.MALFORMED

    if not isinstance(parsed, dict):
        return None, JobSignError.MALFORMED

    if secret:
        if not _is_signed_envelope(parsed):
            return None, JobSignError.UNSIGNED
        version = parsed.get("v")
        if version != SIGNATURE_VERSION:
            return None, JobSignError.VERSION_MISMATCH
        job = parsed.get("job")
        if not isinstance(job, dict):
            return None, JobSignError.MALFORMED
        expected = parsed.get("sig")
        if not isinstance(expected, str):
            return None, JobSignError.MALFORMED
        actual = compute_signature(job, secret)
        if not hmac.compare_digest(actual, expected):
            return None, JobSignError.INVALID_SIGNATURE
        return job, None

    # Dev / unsigned mode: accept a plain job dict.
    if _is_signed_envelope(parsed):
        job = parsed.get("job")
        if isinstance(job, dict):
            return job, None
        return None, JobSignError.MALFORMED
    return parsed, None


def peek_job(raw: str) -> dict[str, Any] | None:
    """Return job fields from a queue payload without verifying the signature."""
    try:
        parsed: Any = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if _is_signed_envelope(parsed):
        job = parsed.get("job")
        return job if isinstance(job, dict) else None
    return parsed


def _is_signed_envelope(parsed: dict[str, Any]) -> bool:
    return "v" in parsed and "job" in parsed and "sig" in parsed
