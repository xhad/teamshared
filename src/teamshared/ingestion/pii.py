"""Lightweight, dependency-free PII and secret detection + redaction.

Regex-based and intentionally conservative: it catches the common high-risk
shapes (emails, phones, SSNs, card numbers, cloud keys, private keys, bearer
tokens). It is a guardrail, not a compliance-grade DLP engine -- enterprise
tiers can swap in a real classifier behind the same interface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer_token": re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|tsk_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b"),
}

# Secret types that should never be stored even redacted (block, don't redact).
_SECRET_TYPES = {"aws_key", "private_key", "bearer_token"}


@dataclass(frozen=True)
class PIIFinding:
    kind: str
    is_secret: bool
    count: int


def scan_pii(text: str) -> list[PIIFinding]:
    findings: list[PIIFinding] = []
    for kind, pattern in _PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            findings.append(
                PIIFinding(kind=kind, is_secret=kind in _SECRET_TYPES, count=len(matches))
            )
    return findings


def has_hard_secret(findings: list[PIIFinding]) -> bool:
    return any(f.is_secret for f in findings)


def redact_pii(text: str) -> str:
    redacted = text
    for kind, pattern in _PATTERNS.items():
        redacted = pattern.sub(f"[REDACTED:{kind}]", redacted)
    return redacted
