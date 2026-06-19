"""Hydrate ontology_entities from existing wiki subjects and memory tags."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from teamshared.memory.ontology import OntologyStore
from teamshared.memory.vectorstore import VectorStore
from teamshared.memory.wiki import slugify

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_GITHUB_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")


@dataclass(frozen=True)
class BackfillCandidate:
    name: str
    kind_name: str
    properties: dict[str, Any]
    auto_approve: bool


def infer_kind(subject: str, *, tags: list[str] | None = None) -> BackfillCandidate:
    """Rule-based kind inference without an LLM."""
    name = subject.strip()
    props: dict[str, Any] = {"subject": name}
    if _EMAIL_RE.match(name):
        return BackfillCandidate(name, "Person", {**props, "email": name}, True)
    if _GITHUB_REPO_RE.match(name):
        return BackfillCandidate(name, "Repository", {**props, "github": name}, True)
    for tag in tags or []:
        if tag.startswith("github:"):
            repo = tag.split(":", 1)[1]
            return BackfillCandidate(
                name, "Repository", {**props, "github": repo}, True
            )
        if tag.startswith("repo:"):
            slug = tag.split(":", 1)[1]
            return BackfillCandidate(
                name, "Repository", {**props, "slug": slug}, True
            )
    return BackfillCandidate(name, "Memory", props, True)


async def collect_candidates(
    vector_store: VectorStore,
    org_id: UUID,
    *,
    subject_limit: int = 500,
) -> list[BackfillCandidate]:
    """Build deduplicated backfill candidates from wiki subjects."""
    subjects = await vector_store.list_subjects(org_id, limit=subject_limit)
    seen_slugs: set[str] = set()
    out: list[BackfillCandidate] = []
    for row in subjects:
        subject = (row.get("subject") or "").strip()
        if not subject:
            continue
        slug = slugify(subject)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        records = await vector_store.list_by_subject(org_id, subject, limit=5)
        tags: list[str] = []
        for rec in records:
            tags.extend(rec.tags or [])
        out.append(infer_kind(subject, tags=tags))
    return out


async def run_backfill(
    *,
    ontology: OntologyStore,
    vector_store: VectorStore,
    org_id: UUID,
    dry_run: bool = True,
    subject_limit: int = 500,
    created_by: str = "ontology-backfill",
) -> dict[str, int]:
    """Upsert entities from inferred wiki subjects. Idempotent on slug."""
    candidates = await collect_candidates(
        vector_store, org_id, subject_limit=subject_limit
    )
    counts = {"candidates": len(candidates), "created": 0, "skipped": 0}
    for cand in candidates:
        if dry_run:
            counts["created"] += 1
            continue
        row = await ontology.propose_entity(
            org_id,
            kind_name=cand.kind_name,
            name=cand.name,
            properties=cand.properties,
            created_by=created_by,
            auto_approve=cand.auto_approve,
        )
        if row.get("status") == "active":
            counts["created"] += 1
        else:
            counts["skipped"] += 1
    return counts
