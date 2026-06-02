"""Curated wiki pages over :class:`TenantDb` (RLS-enforced).

The materialized layer behind ``/app/wiki``: the :class:`CuratorWorker`
synthesizes a subject's facts and episodes into one canonical markdown article
and stores it here. Every curation is a new version row keyed by
``(org_id, slug, version)`` so page history is free; the latest version per slug
is the live page. ``sources`` keeps the contributing ``memory_item`` ids so a
page can be recomputed from raw memory.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb

_FIELDS = ("id", "slug", "version", "title", "body_md", "sources", "updated_by", "updated_at")
_SELECT = "id, slug, version, title, body_md, sources, updated_by, updated_at"


def slugify(subject: str) -> str:
    """URL-safe slug for a memory subject (canonical wiki page key)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (subject or "").lower()).strip("-")
    return slug or "untitled"


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    d = dict(zip(_FIELDS, row, strict=False))
    d["id"] = str(d["id"])
    d["sources"] = [str(s) for s in (d.get("sources") or [])]
    return d


class WikiStore:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def upsert_page(
        self,
        org_id: UUID,
        *,
        slug: str,
        title: str,
        body_md: str,
        sources: list[UUID] | list[str] | None = None,
        updated_by: str = "curator",
    ) -> dict[str, Any]:
        """Write a new version of ``slug``'s page (version = prior max + 1)."""
        source_ids = [str(s) for s in (sources or [])]
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM wiki_pages WHERE slug = %s",
                (slug,),
            )
            row = await cur.fetchone()
            next_version = int(row[0]) if row else 1
            cur = await conn.execute(
                f"INSERT INTO wiki_pages "
                f"(org_id, slug, version, title, body_md, sources, updated_by) "
                f"VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING {_SELECT}",
                (str(org_id), slug, next_version, title, body_md, source_ids, updated_by),
            )
            inserted = await cur.fetchone()
        if inserted is None:
            raise RuntimeError("INSERT did not return a row")
        return _row(inserted)

    async def get_page(
        self, org_id: UUID, slug: str, version: int | None = None
    ) -> dict[str, Any] | None:
        """Latest page for ``slug`` (or a specific ``version``)."""
        async with self.db.org(org_id) as conn:
            if version is None:
                cur = await conn.execute(
                    f"SELECT {_SELECT} FROM wiki_pages WHERE slug = %s "
                    f"ORDER BY version DESC LIMIT 1",
                    (slug,),
                )
            else:
                cur = await conn.execute(
                    f"SELECT {_SELECT} FROM wiki_pages WHERE slug = %s AND version = %s",
                    (slug, version),
                )
            row = await cur.fetchone()
        return _row(row) if row else None

    async def list_pages(self, org_id: UUID, *, limit: int = 200) -> list[dict[str, Any]]:
        """Latest version of every page, most recently updated first."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT DISTINCT ON (slug) {_SELECT} FROM wiki_pages "
                f"ORDER BY slug, version DESC LIMIT %s",
                (limit,),
            )
            rows = await cur.fetchall()
        pages = [_row(r) for r in rows]
        pages.sort(key=lambda p: str(p.get("updated_at") or ""), reverse=True)
        return pages

    async def list_versions(self, org_id: UUID, slug: str) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_SELECT} FROM wiki_pages WHERE slug = %s ORDER BY version DESC",
                (slug,),
            )
            rows = await cur.fetchall()
        return [_row(r) for r in rows]

    async def stats(self, org_id: UUID) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT COUNT(DISTINCT slug), COUNT(*) FROM wiki_pages"
            )
            row = await cur.fetchone()
        return {"pages": int(row[0]) if row else 0, "versions": int(row[1]) if row else 0}
