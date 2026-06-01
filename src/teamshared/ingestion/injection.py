"""Prompt-injection / memory-poisoning screening for ingested content.

Memory is the highest-leverage injection vector: poison a stored "fact" once
and every future agent that recalls it is affected. We score incoming content
for instruction-injection shapes; high-risk content is quarantined for human
approval rather than silently trusted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions", re.I),
    re.compile(r"disregard\s+(?:the\s+)?(?:system|previous)\s+(?:prompt|instructions)", re.I),
    re.compile(r"you\s+are\s+now\s+", re.I),
    re.compile(r"new\s+instructions\s*:", re.I),
    re.compile(r"system\s+prompt\s*:", re.I),
    re.compile(r"(?:reveal|print|exfiltrate|leak)\s+(?:the\s+)?(?:system\s+prompt|secrets?|api[_\s]?keys?)", re.I),
    re.compile(r"\bact\s+as\s+(?:an?\s+)?(?:admin|root|developer\s+mode|dan)\b", re.I),
    re.compile(r"override\s+(?:safety|guardrails?|permissions?)", re.I),
]


@dataclass(frozen=True)
class InjectionVerdict:
    risk: float            # 0.0 .. 1.0
    matched: list[str]
    quarantine: bool


def screen_injection(text: str, *, threshold: float = 0.5) -> InjectionVerdict:
    matched = [p.pattern for p in _INJECTION_PATTERNS if p.search(text)]
    # Each distinct hit adds risk; saturates at 1.0.
    risk = min(1.0, 0.34 * len(matched))
    return InjectionVerdict(risk=risk, matched=matched, quarantine=risk >= threshold)
