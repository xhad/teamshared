"""Repo-scoped durable memory: auto-tagging on write + soft boost on recall.

Memories carry a normalized ``repo:<slug>`` tag (no schema change — it rides
the existing ``tags`` plumbing). ``memory_remember(repo=...)`` attaches it;
``memory_recall(repo=...)`` boosts records that have it without hiding anything.
"""

from __future__ import annotations

import pytest

from teamshared.memory.agent_state import REPO_TAG_PREFIX, repo_tag, validate_repo
from teamshared.memory.facade import _REPO_BOOST, _rerank, _with_repo_tag
from teamshared.memory.types import MemoryRecord


def _mk(score: float, *, tags: list[str] | None = None, pillar: str = "semantic") -> MemoryRecord:
    return MemoryRecord(
        id=f"{pillar}-{score}-{','.join(tags or [])}",
        pillar=pillar,  # type: ignore[arg-type]
        content="x",
        score=score,
        tags=tags or [],
    )


def test_repo_tag_is_prefixed_slug() -> None:
    assert repo_tag("Users-chad-code-sapien-teamshared") == (
        f"{REPO_TAG_PREFIX}Users-chad-code-sapien-teamshared"
    )


def test_repo_tag_rejects_invalid_slug() -> None:
    with pytest.raises(ValueError):
        repo_tag("not a slug/with spaces")
    with pytest.raises(ValueError):
        validate_repo("")


def test_with_repo_tag_appends_and_dedups() -> None:
    assert _with_repo_tag(["a"], "myrepo") == ["a", "repo:myrepo"]
    # Already present: not duplicated.
    assert _with_repo_tag(["repo:myrepo"], "myrepo") == ["repo:myrepo"]


def test_with_repo_tag_no_repo_returns_original_or_none() -> None:
    assert _with_repo_tag(["a"], None) == ["a"]
    assert _with_repo_tag(None, None) is None
    assert _with_repo_tag([], None) is None


def test_with_repo_tag_ignores_invalid_slug_but_keeps_memory() -> None:
    # An unparseable slug must not drop the write; tags pass through unchanged.
    assert _with_repo_tag(["a"], "bad slug") == ["a"]
    assert _with_repo_tag(None, "bad slug") is None


def test_rerank_boosts_same_repo_record_above_higher_base_score() -> None:
    # B has the higher raw score; A only wins once boosted for the active repo.
    a = _mk(0.50, tags=["repo:foo"])
    b = _mk(0.60)
    assert _rerank([a, b], k=2, repo="foo")[0].id == a.id
    # Sanity: the boost is what flips it (0.50 * 1.3 > 0.60).
    assert 0.50 * _REPO_BOOST > 0.60


def test_rerank_without_repo_leaves_higher_base_on_top() -> None:
    a = _mk(0.50, tags=["repo:foo"])
    b = _mk(0.60)
    assert _rerank([a, b], k=2)[0].id == b.id


def test_rerank_hides_nothing_when_boosting() -> None:
    # Cross-repo and un-scoped records still appear; boost only reorders.
    a = _mk(0.50, tags=["repo:foo"])
    b = _mk(0.60, tags=["repo:other"])
    c = _mk(0.55)
    out = _rerank([a, b, c], k=10, repo="foo")
    assert {r.id for r in out} == {a.id, b.id, c.id}
    assert out[0].id == a.id


def test_rerank_invalid_repo_is_a_noop() -> None:
    a = _mk(0.50, tags=["repo:foo"])
    b = _mk(0.60)
    assert _rerank([a, b], k=2, repo="bad slug")[0].id == b.id


def test_with_scope_tags_via_repo_only_matches_with_repo_tag_helper() -> None:
    from teamshared.memory.facade import _with_scope_tags

    assert _with_scope_tags(["a"], repo="myrepo") == _with_repo_tag(["a"], "myrepo")
