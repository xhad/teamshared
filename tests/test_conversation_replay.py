"""Unit tests for conversation replay harness (no live server)."""

from __future__ import annotations

from unittest.mock import patch

import fakeredis.aioredis
import pytest

from eval.conversation_replay_lib import (
    load_fixture,
    parse_turns,
    replay_engine,
    report_to_dict,
    score_expect_any,
    session_cost_summary,
    token_count_messages,
    token_reduction_pct,
    turn_labels_from_fixture,
)
from teamshared.config import Settings
from teamshared.memory import working as working_mod
from teamshared.memory.working import WorkingMemory


def test_parse_turns_shorthand_and_generate() -> None:
    turns = parse_turns(
        [
            {"user": "hello"},
            {"assistant": "hi"},
            {"tool": {"name": "Shell", "generate": "grep_json_500"}},
        ]
    )
    assert turns[0]["role"] == "user"
    assert turns[1]["role"] == "assistant"
    assert turns[2]["role"] == "tool"
    assert turns[2]["tool_name"] == "Shell"
    assert len(turns[2]["content"]) > 5000


def test_token_reduction_on_fat_thread(tmp_path) -> None:
    fixture_path = tmp_path / "fat.yaml"
    fixture_path.write_text(
        """
name: fat
turns:
  - user: find handlers
  - tool:
      name: Shell
      generate: grep_json_500
""",
        encoding="utf-8",
    )
    fixture = load_fixture(str(fixture_path))
    messages = parse_turns(fixture["turns"])
    baseline = token_count_messages(messages)
    assert baseline > 1000


@pytest.mark.asyncio
async def test_replay_engine_reduces_tokens() -> None:
    fixture = {
        "name": "engine-fat",
        "turns": [
            {"user": "find handlers"},
            {"tool": {"name": "Shell", "generate": "grep_json_500"}},
        ],
    }
    settings = Settings(
        _env_file=None,
        redis_url="redis://fake",
        mcp_tool_output_normalize_enabled=True,
        compress_min_chars=800,
    )
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def _from_url(url: str, **kwargs: object) -> fakeredis.aioredis.FakeRedis:
        return fake

    with patch.object(working_mod.redis, "from_url", side_effect=_from_url):
        working = WorkingMemory(settings.redis_url, default_ttl=3600)
        await working.connect()
        try:
            report = await replay_engine(
                fixture, settings=settings, working=working, org_id="00000000-0000-0000-0000-000000000001"
            )
        finally:
            await working.close()

    assert report.baseline_final_tokens > report.memory_final_tokens
    assert report.token_reduction_pct >= 30.0
    assert len(report.checkpoints) == 2


def test_score_expect_any() -> None:
    assert score_expect_any("use port 5433 for postgres", ["5433"])
    assert not score_expect_any("use port 5432", ["5433"])


def test_example_fixture_loads() -> None:
    fixture = load_fixture("eval/conversation_replay.example.yaml")
    assert fixture["name"] == "integration-test-thread"
    turns = parse_turns(fixture["turns"])
    assert len(turns) == 5
    assert token_reduction_pct(1000, 400) == 60.0


def test_teamshared_fixture_loads() -> None:
    fixture = load_fixture("eval/conversation_replay.teamshared.yaml")
    assert fixture["name"] == "teamshared-tribal-knowledge-debug"
    labels = turn_labels_from_fixture(fixture)
    assert labels[0].startswith("user:")
    assert any("grep_json_500" in label for label in labels)
    assert len(parse_turns(fixture["turns"])) == 10


def test_build_dashboard_embeds_json() -> None:
    from eval.conversation_replay_report import build_dashboard

    runs = [
        {
            "fixture": "test",
            "mode": "engine",
            "turn_count": 1,
            "baseline_final_tokens": 100,
            "memory_final_tokens": 50,
            "token_reduction_pct": 50.0,
            "checkpoints": [
                {
                    "turn": 1,
                    "label": "user: repo's tests",
                    "baseline_tokens": 100,
                    "memory_tokens": 50,
                    "saved_pct": 50.0,
                }
            ],
            "passed": True,
        }
    ]
    html = build_dashboard(runs, recorded_at="test-stamp")
    assert 'id="replay-data"' in html
    assert "integration-test-thread" not in html
    assert "repo's tests" in html
    assert "window.__REPLAY_DATA__" not in html


@pytest.mark.asyncio
async def test_report_to_dict_includes_labels() -> None:
    fixture = {
        "name": "mini",
        "turns": [
            {"user": "hello"},
            {"tool": {"name": "Shell", "generate": "grep_json_500"}},
        ],
    }
    settings = Settings(
        _env_file=None,
        redis_url="redis://fake",
        mcp_tool_output_normalize_enabled=True,
        compress_min_chars=800,
    )
    fake = fakeredis.aioredis.FakeRedis(decode_responses=True)

    def _from_url(url: str, **kwargs: object) -> fakeredis.aioredis.FakeRedis:
        return fake

    with patch.object(working_mod.redis, "from_url", side_effect=_from_url):
        working = WorkingMemory(settings.redis_url, default_ttl=3600)
        await working.connect()
        try:
            report = await replay_engine(
                fixture, settings=settings, working=working, org_id="00000000-0000-0000-0000-000000000001"
            )
        finally:
            await working.close()

    data = report_to_dict(report, fixture, fixture_path="mini.yaml")
    assert data["fixture"] == "mini"
    assert len(data["checkpoints"]) == 2
    assert data["checkpoints"][1]["label"].startswith("tool Shell")
    assert data["passed"] is True
    assert data["baseline_session_tokens"] >= data["baseline_final_tokens"]
    assert "memory_est_input_usd" in data


def test_session_cost_summary() -> None:
    from eval.conversation_replay_lib import Checkpoint, ReplayReport

    report = ReplayReport(name="x", mode="engine", turn_count=2)
    report.checkpoints = [
        Checkpoint(turn=1, baseline_tokens=100, memory_tokens=80),
        Checkpoint(turn=2, baseline_tokens=500, memory_tokens=200),
    ]
    costs = session_cost_summary(report)
    assert costs["baseline_session_tokens"] == 600
    assert costs["memory_session_tokens"] == 280
    assert costs["session_token_reduction_pct"] == 53.33
    assert not costs["memory_more_expensive"]
