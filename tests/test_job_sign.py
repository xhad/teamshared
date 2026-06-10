"""HMAC job signing for distill/curate queues."""

from __future__ import annotations

import json

import pytest

from teamshared.queue.job_sign import (
    SIGNATURE_VERSION,
    JobSignError,
    compute_signature,
    decode_job,
    encode_job,
)


def test_encode_without_secret_is_plain_json() -> None:
    job = {"org_id": "o1", "session_id": "sess_x", "attempts": 0}
    raw = encode_job(job, secret=None)
    assert json.loads(raw) == job


def test_encode_with_secret_wraps_envelope() -> None:
    job = {"org_id": "o1", "subject": "infra"}
    raw = encode_job(job, secret="test-secret")
    parsed = json.loads(raw)
    assert parsed["v"] == SIGNATURE_VERSION
    assert parsed["job"] == job
    assert parsed["sig"] == compute_signature(job, "test-secret")


def test_decode_roundtrip() -> None:
    job = {"org_id": "o1", "session_id": "sess_y", "turn_count": 3}
    secret = "signing-key"
    raw = encode_job(job, secret=secret)
    decoded, err = decode_job(raw, secret=secret)
    assert err is None
    assert decoded == job


def test_decode_rejects_tampered_payload() -> None:
    job = {"org_id": "o1", "session_id": "sess_z"}
    secret = "signing-key"
    raw = encode_job(job, secret=secret)
    parsed = json.loads(raw)
    parsed["job"]["org_id"] = "evil-org"
    tampered = json.dumps(parsed)
    decoded, err = decode_job(tampered, secret=secret)
    assert decoded is None
    assert err == JobSignError.INVALID_SIGNATURE


def test_decode_rejects_unsigned_when_secret_required() -> None:
    plain = json.dumps({"org_id": "o1", "session_id": "sess_a"})
    decoded, err = decode_job(plain, secret="required")
    assert decoded is None
    assert err == JobSignError.UNSIGNED


def test_decode_accepts_plain_when_unsigned_mode() -> None:
    job = {"org_id": "o1", "subject": "wiki"}
    raw = json.dumps(job)
    decoded, err = decode_job(raw, secret=None)
    assert err is None
    assert decoded == job


def test_decode_accepts_envelope_without_verify_in_unsigned_mode() -> None:
    job = {"org_id": "o1", "subject": "wiki"}
    raw = encode_job(job, secret="prod-only")
    decoded, err = decode_job(raw, secret=None)
    assert err is None
    assert decoded == job


@pytest.mark.parametrize("raw", ["not-json", "[]"])
def test_decode_malformed(raw: str) -> None:
    decoded, err = decode_job(raw, secret="x")
    assert decoded is None
    assert err == JobSignError.MALFORMED


def test_decode_incomplete_envelope_is_unsigned() -> None:
    decoded, err = decode_job('{"v":1}', secret="x")
    assert decoded is None
    assert err == JobSignError.UNSIGNED


def test_signature_is_stable_over_key_order() -> None:
    a = {"b": 2, "a": 1, "org_id": "o"}
    b = {"org_id": "o", "a": 1, "b": 2}
    secret = "k"
    assert compute_signature(a, secret) == compute_signature(b, secret)
