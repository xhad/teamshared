"""Types for context compression (CCR-backed prompt shrink-wrap)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompressStats:
    """Per-request compression metrics."""

    original_chars: int = 0
    compressed_chars: int = 0
    messages_touched: int = 0
    refs: list[str] = field(default_factory=list)

    @property
    def chars_saved(self) -> int:
        return max(0, self.original_chars - self.compressed_chars)

    @property
    def ratio(self) -> float:
        if self.original_chars <= 0:
            return 1.0
        return round(self.compressed_chars / self.original_chars, 4)


@dataclass
class CompressResult:
    """Output of ``compress_messages``."""

    messages: list[dict[str, Any]]
    stats: CompressStats
    compressed: bool
