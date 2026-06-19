"""Memory ingestion: the guarded write path.

Everything entering durable memory -- explicit, agent-authored, extracted, or
connector-sourced -- flows through :class:`~teamshared.ingestion.pipeline.IngestionPipeline`,
which dedupes, scans for PII/secrets, screens for prompt injection (audit-only),
embeds as ``active``, and audits. Hard secrets are rejected; injection hits are
logged but do not block storage.
"""

from teamshared.ingestion.injection import InjectionVerdict, screen_injection
from teamshared.ingestion.pii import PIIFinding, redact_pii, scan_pii
from teamshared.ingestion.pipeline import (
    IngestionPipeline,
    IngestionRejected,
    IngestionResult,
    ProcedureIngestionResult,
    SkillIngestionResult,
)

__all__ = [
    "IngestionPipeline",
    "IngestionRejected",
    "IngestionResult",
    "InjectionVerdict",
    "PIIFinding",
    "ProcedureIngestionResult",
    "SkillIngestionResult",
    "redact_pii",
    "scan_pii",
    "screen_injection",
]
