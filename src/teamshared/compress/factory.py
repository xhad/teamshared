"""Factory helpers for compression stores."""

from __future__ import annotations

from teamshared.compress.ccr_store import CcrStore
from teamshared.config import Settings
from teamshared.memory.working import WorkingMemory


def ccr_store_from_working(settings: Settings, working: WorkingMemory) -> CcrStore:
    return CcrStore(working.client, ttl_seconds=settings.compress_ccr_ttl_seconds)
