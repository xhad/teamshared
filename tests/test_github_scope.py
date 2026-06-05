"""GitHub-scoped durable memory: auto-tagging on write + soft boost on recall."""

from __future__ import annotations

import pytest

from teamshared.memory.agent_state import GITHUB_TAG_PREFIX, github_tag, validate_github
from teamshared.memory.facade import _GITHUB_BOOST, _rerank, _with_scope_tags
from teamshared.memory.types import MemoryRecord


def _mk(score: float, *, tags: list[str] | None = None, pillar: str = "semantic") -> MemoryRecord:
    return MemoryRecord(
        id=f"{pillar}-{score}-{','.join(tags or [])}",
        pillar=pillar,  # type: ignore[arg-type]
        content="x",
        score=score,
        tags=tags or [],
    )


def test_github_tag_is_prefixed_owner_repo() -> None:
    assert github_tag("xhad/teamshared") == f"{GITHUB_TAG_PREFIX}xhad/teamshared"


def test_github_tag_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        github_tag("not-valid")
    with pytest.raises(ValueError):
        validate_github("")


def test_with_scope_tags_appends_github_and_dedups() -> None:
    assert _with_scope_tags(["a"], github="xhad/teamshared") == [
        "a",
        "github:xhad/teamshared",
    ]
    assert _with_scope_tags(["github:xhad/teamshared"], github="xhad/teamshared") == [
        "github:xhad/teamshared",
    ]


def test_with_scope_tags_repo_and_github_together() -> None:
    tags = _with_scope_tags(None, repo="myrepo", github="xhad/teamshared")
    assert tags == ["repo:myrepo", "github:xhad/teamshared"]


def test_with_scope_tags_ignores_invalid_github() -> None:
    assert _with_scope_tags(["a"], github="bad") == ["a"]


def test_rerank_boosts_github_tagged_record() -> None:
    a = _mk(0.50, tags=["github:xhad/teamshared"])
    b = _mk(0.60)
    assert _rerank([a, b], k=2, github="xhad/teamshared")[0].id == a.id
    assert 0.50 * _GITHUB_BOOST > 0.60


def test_rerank_github_and_repo_boosts_stack() -> None:
    a = _mk(0.40, tags=["repo:foo", "github:xhad/teamshared"])
    b = _mk(0.60)
    out = _rerank([a, b], k=2, repo="foo", github="xhad/teamshared")
    assert out[0].id == a.id
