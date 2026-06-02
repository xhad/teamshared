"""Memory ingestion: the guarded write path.

Everything entering durable memory -- explicit, agent-authored, extracted, or
connector-sourced -- flows through :class:`~teamshared.ingestion.pipeline.IngestionPipeline`,
which dedupes, scans for PII/secrets, screens for prompt injection, classifies,
routes high-impact or low-confidence items to the approval queue, embeds, and
audits. "Memory is context, not authority": untrusted content is quarantined,
never silently trusted.
"""

from teamshared.ingestion.approvals import ApprovalQueue
from teamshared.ingestion.injection import InjectionVerdict, screen_injection
from teamshared.ingestion.pii import PIIFinding, redact_pii, scan_pii
from teamshared.ingestion.pipeline import (
    IngestionPipeline,
    IngestionRejected,
    IngestionResult,
    ProcedureIngestionResult,
)

__all__ = [
    "ApprovalQueue",
    "IngestionPipeline",
    "IngestionRejected",
    "IngestionResult",
    "ProcedureIngestionResult",
    "InjectionVerdict",
    "PIIFinding",
    "redact_pii",
    "scan_pii",
    "screen_injection",
]
