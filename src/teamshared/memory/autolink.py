"""Zero-LLM entity extraction and graph edge inference on memory writes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from teamshared.logging import get_logger

log = get_logger(__name__)


class GraphBackend(Protocol):
    async def add_relation(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        org_id: str,
        agent: str,
        weight: float = 1.0,
    ) -> None: ...

    async def related(
        self, name: str, *, org_id: str, depth: int = 2, limit: int = 20
    ) -> list[Any]: ...

_WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]]*)?\]\]")
_AT_MENTION_RE = re.compile(r"(?<!\w)@([a-zA-Z][\w.-]{1,63})")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_WORKS_AT_RE = re.compile(
    r"(\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+works?\s+at\s+(\b[A-Z][\w][\w\s.-]*)",
    re.IGNORECASE,
)
_REPO_TAG_RE = re.compile(r"repo:([\w-]+)")
_GITHUB_TAG_RE = re.compile(r"github:([\w.-]+/[\w.-]+)")


@dataclass(frozen=True)
class EntityRef:
    subject: str
    predicate: str
    object_: str


def extract_entity_refs(
    content: str,
    *,
    subject: str | None = None,
    tags: list[str] | None = None,
) -> list[EntityRef]:
    """Extract typed entity relationships from markdown memory content."""
    refs: list[EntityRef] = []
    seen: set[tuple[str, str, str]] = set()

    def add(sub: str, pred: str, obj: str) -> None:
        sub, obj = sub.strip(), obj.strip()
        if not sub or not obj or sub.lower() == obj.lower():
            return
        key = (sub.lower(), pred, obj.lower())
        if key in seen:
            return
        seen.add(key)
        refs.append(EntityRef(subject=sub, predicate=pred, object_=obj))

    for match in _WIKILINK_RE.finditer(content):
        target = match.group(1).strip()
        anchor = subject or "unknown"
        add(anchor, "mentions", target)

    for match in _AT_MENTION_RE.finditer(content):
        add(subject or "unknown", "mentions", match.group(1))

    for match in _MD_LINK_RE.finditer(content):
        label = match.group(1).strip()
        if label:
            add(subject or "unknown", "mentions", label)

    for match in _WORKS_AT_RE.finditer(content):
        add(match.group(1).strip(), "works_at", match.group(2).strip())

    if subject:
        for tag in tags or []:
            m = _REPO_TAG_RE.match(tag)
            if m:
                add(subject, "works_on", m.group(1))
            m = _GITHUB_TAG_RE.match(tag)
            if m:
                add(subject, "works_on", m.group(1))

    return refs


async def apply_autolink(
    graph: GraphBackend | None,
    *,
    content: str,
    subject: str | None,
    tags: list[str] | None,
    org_id: str,
    agent: str,
    allowed_predicates: frozenset[str] | None = None,
    link_validator: Any | None = None,
) -> int:
    """Write inferred edges to the graph store. Returns edge count."""
    if graph is None:
        return 0
    refs = extract_entity_refs(content, subject=subject, tags=tags)
    count = 0
    org_uuid = UUID(org_id)
    for ref in refs:
        if allowed_predicates is not None and ref.predicate not in allowed_predicates:
            continue
        if link_validator is not None:
            check = await link_validator(org_uuid, ref.predicate, ref.subject, ref.object_)
            if not check.allowed:
                log.warning(
                    "autolink_edge_kind_rejected",
                    subject=ref.subject,
                    predicate=ref.predicate,
                    object=ref.object_,
                    error=check.error,
                )
                continue
            if check.warning:
                log.warning(
                    "autolink_edge_kind_warn",
                    subject=ref.subject,
                    predicate=ref.predicate,
                    object=ref.object_,
                    warning=check.warning,
                )
        try:
            await graph.add_relation(
                ref.subject,
                ref.predicate,
                ref.object_,
                org_id=org_id,
                agent=agent,
                weight=1.0,
            )
            count += 1
        except Exception as exc:
            log.warning(
                "autolink_edge_failed",
                subject=ref.subject,
                predicate=ref.predicate,
                object=ref.object_,
                error=str(exc),
            )
    return count
