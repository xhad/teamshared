"""Shared compression-related settings for unit test mocks."""

from __future__ import annotations

from typing import Any

COMPRESS_SETTING_DEFAULTS: dict[str, Any] = {
    "compress_ccr_ttl_seconds": 3600,
    "compress_min_chars": 800,
    "compress_json_max_items": 20,
    "compress_log_max_lines": 40,
    "compress_target_ratio": 0.35,
    "mcp_tool_output_normalize_enabled": True,
    "mcp_tool_output_max_record_chars": 600,
    "llm_prepare_enabled": True,
    "llm_prepare_context_token_budget": 1500,
}


def apply_compress_settings(target: Any) -> None:
    for key, value in COMPRESS_SETTING_DEFAULTS.items():
        setattr(target, key, value)
