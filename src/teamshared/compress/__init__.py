"""Context compression before LLM calls (CCR-backed)."""

from teamshared.compress.engine import compress_messages, compress_text
from teamshared.compress.types import CompressResult, CompressStats

__all__ = ["CompressResult", "CompressStats", "compress_messages", "compress_text"]
