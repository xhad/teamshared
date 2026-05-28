"""Make sure the distill prompt renders cleanly and the JSON parser is strict."""

from __future__ import annotations

import pytest

from teamshared.distill.prompts import SUMMARIZER_SYSTEM, build_user_message
from teamshared.distill.summarizer import SummarizerError, _parse_json


def test_build_user_message_includes_agent_and_topic() -> None:
    msg = build_user_message(
        "cursor",
        "memory plan",
        [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
    )
    assert "AGENT: cursor" in msg
    assert "TOPIC: memory plan" in msg
    assert "(user) hi" in msg
    assert "(assistant) hello" in msg


def test_build_user_message_handles_missing_topic() -> None:
    msg = build_user_message("cursor", None, [])
    assert "TOPIC: (none)" in msg


def test_summarizer_system_mentions_schema() -> None:
    assert "episode" in SUMMARIZER_SYSTEM
    assert "facts" in SUMMARIZER_SYSTEM
    assert "decisions" in SUMMARIZER_SYSTEM


def test_parse_json_rejects_garbage() -> None:
    with pytest.raises(SummarizerError):
        _parse_json("this is not json")


def test_parse_json_accepts_valid() -> None:
    parsed = _parse_json('{"episode": {"summary": "x"}, "facts": [], "decisions": []}')
    assert parsed["episode"]["summary"] == "x"
