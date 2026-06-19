"""Tests for ontology subject backfill helpers."""

from __future__ import annotations

from teamshared.seed.ontology_backfill import infer_kind


def test_infer_kind_email_is_person() -> None:
    cand = infer_kind("alice@example.com")
    assert cand.kind_name == "Person"
    assert cand.auto_approve is True


def test_infer_kind_github_repo() -> None:
    cand = infer_kind("xhad/teamshared")
    assert cand.kind_name == "Repository"


def test_infer_kind_default_memory() -> None:
    cand = infer_kind("teamshared")
    assert cand.kind_name == "Memory"
