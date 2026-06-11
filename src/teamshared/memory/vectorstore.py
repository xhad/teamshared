"""First-party pgvector memory store (the Mem0 replacement).

Owns ``memory_items`` / ``memory_chunks`` / ``memory_embeddings``. Every method
runs inside :meth:`TenantDb.org`, so RLS guarantees org isolation at the
database level. On top of that hard boundary, :meth:`search` applies the
scope/visibility filter *in the SQL WHERE clause*, before the ``ORDER BY
embedding <=> query`` distance sort -- so a candidate from another team/user is
never even scored, let alone returned.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.memory.embeddings import Embedder
from teamshared.memory.hnsw_cache import HnswCache
from teamshared.memory.types import (
    MemoryItem,
    MemoryItemScope,
    MemoryKind,
    MemoryRecord,
    MemorySource,
    Visibility,
)
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)


@dataclass
class ScopeFilter:
    """The set of scopes a principal may read from, used to pre-filter search.

    ``include_shared`` widens the result to any item flagged
    ``visibility='shared'`` or explicitly shared via ``memory_shares``.
    """

    user_id: UUID | None = None
    agent_id: UUID | None = None
    team_ids: list[UUID] = field(default_factory=list)
    project_ids: list[UUID] = field(default_factory=list)
    include_org: bool = True
    include_shared: bool = True

    def where(self, alias: str = "mi") -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if self.include_org:
            clauses.append(f"{alias}.scope = 'org'")
        if self.user_id is not None:
            clauses.append(f"({alias}.scope = 'user' AND {alias}.scope_ref_id = %s)")
            params.append(str(self.user_id))
        if self.agent_id is not None:
            clauses.append(f"({alias}.scope = 'agent' AND {alias}.scope_ref_id = %s)")
            params.append(str(self.agent_id))
        if self.team_ids:
            clauses.append(f"({alias}.scope = 'team' AND {alias}.scope_ref_id = ANY(%s))")
            params.append([str(t) for t in self.team_ids])
        if self.project_ids:
            clauses.append(f"({alias}.scope = 'project' AND {alias}.scope_ref_id = ANY(%s))")
            params.append([str(p) for p in self.project_ids])
        if self.include_shared:
            clauses.append(f"{alias}.visibility = 'shared'")
            clauses.append(
                f"{alias}.id IN (SELECT memory_id FROM memory_shares)"
            )
        if not clauses:
            return "false", []
        return "(" + " OR ".join(clauses) + ")", params


def content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().lower().encode()).hexdigest()


def _vec_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


class VectorStore:
    def __init__(
        self, db: TenantDb, embedder: Embedder, cache: HnswCache | None = None
    ) -> None:
        self.db = db
        self.embedder = embedder
        self.cache = cache

    async def add(
        self,
        *,
        org_id: UUID,
        content: str,
        kind: MemoryKind = "note",
        pillar: str = "semantic",
        scope: MemoryItemScope = "org",
        scope_ref_id: UUID | None = None,
        visibility: Visibility = "private",
        subject: str | None = None,
        tags: list[str] | None = None,
        source: MemorySource = "manual",
        source_ref: dict[str, Any] | None = None,
        confidence: float | None = None,
        importance: float | None = None,
        owner_type: str | None = None,
        owner_id: UUID | None = None,
        creator_type: str | None = None,
        creator_id: UUID | None = None,
        status: str = "active",
        summary: str | None = None,
    ) -> UUID:
        chash = content_hash(content)
        [embedding] = await self.embedder.embed([content])
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO memory_items
                    (org_id, pillar, kind, scope, scope_ref_id, visibility, content, summary,
                     subject, tags, source, source_ref, confidence, importance, owner_type,
                     owner_id, creator_type, creator_id, status, content_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
                """,
                (
                    str(org_id), pillar, kind, scope,
                    str(scope_ref_id) if scope_ref_id else None, visibility, content, summary,
                    subject, tags or [], source,
                    json.dumps(source_ref) if source_ref is not None else None,
                    confidence, importance, owner_type,
                    str(owner_id) if owner_id else None, creator_type,
                    str(creator_id) if creator_id else None, status, chash,
                ),
            )
            row = await cur.fetchone()
            assert row is not None
            memory_id: UUID = row[0]
            cur = await conn.execute(
                "INSERT INTO memory_chunks (org_id, memory_id, ordinal, content) "
                "VALUES (%s,%s,0,%s) RETURNING id",
                (str(org_id), str(memory_id), content),
            )
            crow = await cur.fetchone()
            assert crow is not None
            chunk_id = crow[0]
            await conn.execute(
                "INSERT INTO memory_embeddings (org_id, chunk_id, model, embedding) "
                "VALUES (%s,%s,%s,%s::vector)",
                (str(org_id), str(chunk_id), self.embedder_model, _vec_literal(embedding)),
            )
        if self.cache is not None and status == "active":
            self.cache.add(str(org_id), str(memory_id), embedding)
        return memory_id

    @property
    def embedder_model(self) -> str:
        return getattr(self.embedder, "model", "hash")

    async def find_duplicate(self, org_id: UUID, content: str) -> UUID | None:
        chash = content_hash(content)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id FROM memory_items WHERE content_hash = %s AND status != 'soft_deleted' "
                "LIMIT 1",
                (chash,),
            )
            row = await cur.fetchone()
        return row[0] if row else None

    async def search(
        self,
        *,
        org_id: UUID,
        query: str,
        scope_filter: ScopeFilter,
        k: int = 8,
        pillar: str | None = None,
        time_range: tuple[datetime | None, datetime | None] | None = None,
        author_agent_id: UUID | None = None,
    ) -> list[MemoryRecord]:
        [q_emb] = await self.embedder.embed([query])
        candidates = await self._cache_candidates(org_id, q_emb, k)
        if candidates is not None:
            return await self._search_from_candidates(
                org_id=org_id,
                candidates=candidates,
                scope_filter=scope_filter,
                k=k,
                pillar=pillar,
                time_range=time_range,
                author_agent_id=author_agent_id,
            )
        scope_sql, scope_params = scope_filter.where("mi")
        # Only score vectors produced by the active embedder: distances across
        # different embedding models are not comparable, so mixed rows (e.g.
        # pre-reembed OpenAI vectors next to local ONNX vectors) must never be
        # ranked together. `teamshared reembed` migrates old rows.
        where = ["mi.status = 'active'", "me.model = %s", scope_sql]
        params: list[Any] = [self.embedder_model, *scope_params]
        if pillar:
            where.append("mi.pillar = %s")
            params.append(pillar)
        if author_agent_id is not None:
            where.append("(mi.owner_type = 'agent' AND mi.owner_id = %s)")
            params.append(str(author_agent_id))
        if time_range:
            since, until = time_range
            if since:
                where.append("mi.created_at >= %s")
                params.append(since)
            if until:
                where.append("mi.created_at <= %s")
                params.append(until)
        where_sql = " AND ".join(where)
        sql = f"""
            SELECT DISTINCT ON (mi.id)
                mi.id, mi.pillar, mi.kind, mi.content, mi.subject, mi.tags,
                mi.scope, mi.scope_ref_id, mi.visibility, mi.source, mi.confidence,
                mi.importance, mi.version, mi.status, mi.created_at, a.name AS agent,
                (me.embedding <=> %s::vector) AS distance
            FROM memory_items mi
            JOIN memory_chunks mc ON mc.memory_id = mi.id
            JOIN memory_embeddings me ON me.chunk_id = mc.id
            LEFT JOIN agents a ON a.id = mi.owner_id AND mi.owner_type = 'agent'
            WHERE {where_sql}
            ORDER BY mi.id, distance ASC
        """
        params_with_vec = [_vec_literal(q_emb), *params]
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(sql, params_with_vec)
            rows = await cur.fetchall()
        records = [_row_to_record(r, org_id) for r in rows]
        records.sort(key=lambda r: r.score or 0.0, reverse=True)
        return records[:k]

    async def _cache_candidates(
        self, org_id: UUID, q_emb: list[float], k: int
    ) -> list[tuple[str, float]] | None:
        """ANN candidates from the in-memory HNSW cache, or None to use SQL.

        Over-fetches (8x ``k``, min 64) because the scope/visibility filter is
        applied afterwards in SQL: candidates the caller may not read are
        dropped there, never returned. Any cache failure degrades to the
        pgvector path rather than failing recall.
        """
        if self.cache is None or not self.cache.available:
            return None
        try:
            await self.cache.ensure_hydrated(str(org_id), self.db, self.embedder_model)
            return self.cache.search(str(org_id), q_emb, max(k * 8, 64))
        except Exception:
            log.warning("hnsw_cache_search_failed", org_id=str(org_id), exc_info=True)
            return None

    async def _search_from_candidates(
        self,
        *,
        org_id: UUID,
        candidates: list[tuple[str, float]],
        scope_filter: ScopeFilter,
        k: int,
        pillar: str | None,
        time_range: tuple[datetime | None, datetime | None] | None,
        author_agent_id: UUID | None,
    ) -> list[MemoryRecord]:
        """Re-filter ANN candidate ids through RLS + scope SQL and hydrate rows.

        Authorization stays in Postgres: the candidate list only narrows the
        search space, the WHERE clause decides what the caller may see.
        """
        if not candidates:
            return []
        distance_by_id = {mid: dist for mid, dist in candidates}
        scope_sql, scope_params = scope_filter.where("mi")
        where = ["mi.status = 'active'", "mi.id = ANY(%s)", scope_sql]
        params: list[Any] = [list(distance_by_id.keys()), *scope_params]
        if pillar:
            where.append("mi.pillar = %s")
            params.append(pillar)
        if author_agent_id is not None:
            where.append("(mi.owner_type = 'agent' AND mi.owner_id = %s)")
            params.append(str(author_agent_id))
        if time_range:
            since, until = time_range
            if since:
                where.append("mi.created_at >= %s")
                params.append(since)
            if until:
                where.append("mi.created_at <= %s")
                params.append(until)
        where_sql = " AND ".join(where)
        sql = f"""
            SELECT mi.id, mi.pillar, mi.kind, mi.content, mi.subject, mi.tags,
                   mi.scope, mi.scope_ref_id, mi.visibility, mi.source, mi.confidence,
                   mi.importance, mi.version, mi.status, mi.created_at, a.name AS agent,
                   NULL AS score
            FROM memory_items mi
            LEFT JOIN agents a ON a.id = mi.owner_id AND mi.owner_type = 'agent'
            WHERE {where_sql}
        """
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
        records: list[MemoryRecord] = []
        for r in rows:
            rec = _row_to_record(r, org_id, score_is_distance=False)
            dist = distance_by_id.get(str(rec.id))
            rec.score = (1.0 - dist) if dist is not None else None
            records.append(rec)
        records.sort(key=lambda rec: rec.score or 0.0, reverse=True)
        return records[:k]

    async def keyword_search(
        self,
        *,
        org_id: UUID,
        query: str,
        scope_filter: ScopeFilter,
        k: int = 8,
        author_agent_id: UUID | None = None,
    ) -> list[MemoryRecord]:
        scope_sql, scope_params = scope_filter.where("mi")
        author_sql = ""
        author_params: list[Any] = []
        if author_agent_id is not None:
            author_sql = " AND (mi.owner_type = 'agent' AND mi.owner_id = %s)"
            author_params = [str(author_agent_id)]
        sql = f"""
            SELECT mi.id, mi.pillar, mi.kind, mi.content, mi.subject, mi.tags,
                   mi.scope, mi.scope_ref_id, mi.visibility, mi.source, mi.confidence,
                   mi.importance, mi.version, mi.status, mi.created_at, a.name AS agent,
                   ts_rank(
                     to_tsvector('english', coalesce(mi.content,'') || ' ' || coalesce(mi.summary,'')),
                     plainto_tsquery('english', %s)
                   ) AS rank
            FROM memory_items mi
            LEFT JOIN agents a ON a.id = mi.owner_id AND mi.owner_type = 'agent'
            WHERE mi.status = 'active' AND {scope_sql}{author_sql}
              AND to_tsvector('english', coalesce(mi.content,'') || ' ' || coalesce(mi.summary,''))
                  @@ plainto_tsquery('english', %s)
            ORDER BY rank DESC
            LIMIT %s
        """
        params = [query, *scope_params, *author_params, query, k]
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(sql, params)
            rows = await cur.fetchall()
        # ts_rank, not distance: map rank directly into score slot.
        out: list[MemoryRecord] = []
        for r in rows:
            rec = _row_to_record(r, org_id, score_is_distance=False)
            out.append(rec)
        return out

    async def get(self, org_id: UUID, memory_id: UUID) -> MemoryItem | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id, org_id, pillar, kind, scope, scope_ref_id, visibility, content, "
                "summary, subject, tags, source, source_ref, confidence, importance, owner_type, "
                "owner_id, creator_type, creator_id, status, version, content_hash, expires_at, "
                "created_at FROM memory_items WHERE id = %s",
                (str(memory_id),),
            )
            row = await cur.fetchone()
        return _row_to_item(row) if row else None

    async def soft_delete(self, org_id: UUID, memory_id: UUID) -> bool:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "UPDATE memory_items SET status = 'soft_deleted', deleted_at = now(), "
                "updated_at = now() WHERE id = %s AND status != 'soft_deleted'",
                (str(memory_id),),
            )
            deleted = cur.rowcount > 0
        if deleted and self.cache is not None:
            self.cache.remove(str(org_id), str(memory_id))
        return deleted

    async def update_content(
        self, org_id: UUID, memory_id: UUID, *, content: str, editor_id: UUID | None = None
    ) -> bool:
        """Edit content, snapshotting the prior version and re-embedding."""
        [embedding] = await self.embedder.embed([content])
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT version, content, summary FROM memory_items WHERE id = %s",
                (str(memory_id),),
            )
            row = await cur.fetchone()
            if row is None:
                return False
            version, old_content, old_summary = row
            await conn.execute(
                "INSERT INTO memory_versions (org_id, memory_id, version, content, summary, metadata, created_by) "
                "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s) ON CONFLICT (memory_id, version) DO NOTHING",
                (
                    str(org_id), str(memory_id), version, old_content, old_summary,
                    json.dumps({}), str(editor_id) if editor_id else None,
                ),
            )
            await conn.execute(
                "UPDATE memory_items SET content = %s, version = version + 1, "
                "content_hash = %s, updated_at = now() WHERE id = %s",
                (content, content_hash(content), str(memory_id)),
            )
            cur = await conn.execute(
                "SELECT mc.id FROM memory_chunks mc WHERE mc.memory_id = %s ORDER BY ordinal LIMIT 1",
                (str(memory_id),),
            )
            crow = await cur.fetchone()
            if crow is not None:
                chunk_id = crow[0]
                await conn.execute(
                    "UPDATE memory_chunks SET content = %s WHERE id = %s",
                    (content, str(chunk_id)),
                )
                await conn.execute("DELETE FROM memory_embeddings WHERE chunk_id = %s", (str(chunk_id),))
                await conn.execute(
                    "INSERT INTO memory_embeddings (org_id, chunk_id, model, embedding) "
                    "VALUES (%s,%s,%s,%s::vector)",
                    (str(org_id), str(chunk_id), self.embedder_model, _vec_literal(embedding)),
                )
        if self.cache is not None:
            self.cache.add(str(org_id), str(memory_id), embedding)
        return True

    async def set_status(self, org_id: UUID, memory_id: UUID, status: str) -> bool:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "UPDATE memory_items SET status = %s, updated_at = now() WHERE id = %s",
                (status, str(memory_id)),
            )
            changed = cur.rowcount > 0
        if changed and self.cache is not None:
            if status == "active":
                # Re-activation needs the vector back; cheapest correct move is
                # to rehydrate the whole org on the next search.
                self.cache.invalidate(str(org_id))
            else:
                self.cache.remove(str(org_id), str(memory_id))
        return changed

    async def list_episodes(
        self,
        *,
        org_id: UUID,
        topic: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
        author_agent_id: UUID | None = None,
    ) -> list[MemoryRecord]:
        """Browse the episodic timeline (pillar='episodic'), newest first."""
        where = ["mi.status = 'active'", "mi.pillar = 'episodic'"]
        params: list[Any] = []
        if topic:
            where.append("(mi.subject ILIKE %s OR mi.content ILIKE %s)")
            like = f"%{topic}%"
            params.extend([like, like])
        if since:
            where.append("mi.created_at >= %s")
            params.append(since)
        if until:
            where.append("mi.created_at <= %s")
            params.append(until)
        if author_agent_id is not None:
            where.append("(mi.owner_type = 'agent' AND mi.owner_id = %s)")
            params.append(str(author_agent_id))
        where_sql = " AND ".join(where)
        sql = f"""
            SELECT mi.id, mi.pillar, mi.kind, mi.content, mi.subject, mi.tags,
                   mi.scope, mi.scope_ref_id, mi.visibility, mi.source, mi.confidence,
                   mi.importance, mi.version, mi.status, mi.created_at, a.name AS agent,
                   NULL AS score
            FROM memory_items mi
            LEFT JOIN agents a ON a.id = mi.owner_id AND mi.owner_type = 'agent'
            WHERE {where_sql}
            ORDER BY mi.created_at DESC
            LIMIT %s
        """
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(sql, [*params, limit])
            rows = await cur.fetchall()
        return [_row_to_record(r, org_id, score_is_distance=False) for r in rows]

    async def stats(self, org_id: UUID) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT count(*) FILTER (WHERE status='active'), "
                "count(*) FILTER (WHERE status='pending_approval'), "
                "count(*) FILTER (WHERE status='quarantined') FROM memory_items"
            )
            row = await cur.fetchone()
        return {
            "active": int(row[0]) if row else 0,
            "pending_approval": int(row[1]) if row else 0,
            "quarantined": int(row[2]) if row else 0,
        }

    async def health(self, org_id: UUID) -> str:
        """Confirm the durable semantic/episodic store is queryable under RLS.

        Cheap existence check on the vector schema (distinct from the plain
        ``SELECT 1`` Postgres probe: this fails if the memory migrations never
        ran). Returns the active embedder model so callers can see which
        embedding backend is in use.
        """
        async with self.db.org(org_id) as conn:
            cur = await conn.execute("SELECT 1 FROM memory_embeddings LIMIT 1")
            await cur.fetchone()
        return self.embedder_model

    async def pillar_stats(self, org_id: UUID) -> dict[str, Any]:
        """Per-pillar / per-agent / per-kind / top-tag breakdown for the dashboard.

        Same shape as the legacy Mem0 ``stats`` so the ``/memory`` renderer is
        unchanged, but sourced from ``memory_items`` (active rows) under RLS.
        """
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT pillar, COUNT(*) FROM memory_items WHERE status='active' GROUP BY 1"
            )
            by_pillar = {str(r[0] or "semantic"): int(r[1]) for r in await cur.fetchall()}
            cur = await conn.execute(
                "SELECT a.name, COUNT(*) FROM memory_items mi "
                "JOIN agents a ON a.id = mi.owner_id AND mi.owner_type = 'agent' "
                "WHERE mi.status='active' GROUP BY 1 ORDER BY 2 DESC"
            )
            by_agent = {str(r[0]): int(r[1]) for r in await cur.fetchall()}
            cur = await conn.execute(
                "SELECT kind, COUNT(*) FROM memory_items "
                "WHERE status='active' AND pillar='semantic' AND kind IS NOT NULL "
                "GROUP BY 1 ORDER BY 2 DESC"
            )
            by_kind = {str(r[0]): int(r[1]) for r in await cur.fetchall()}
            cur = await conn.execute(
                "SELECT tag, COUNT(*) FROM memory_items, unnest(tags) AS tag "
                "WHERE status='active' GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
            )
            tags = [(str(r[0]), int(r[1])) for r in await cur.fetchall()]
        return {
            "by_pillar": by_pillar,
            "by_agent": by_agent,
            "by_kind": by_kind,
            "tags": tags,
            "semantic": int(by_pillar.get("semantic", 0)),
            "episodic": int(by_pillar.get("episodic", 0)),
            "total": sum(by_pillar.values()),
        }

    async def list_recent(
        self, org_id: UUID, *, limit: int = 10, pillar: str | None = None
    ) -> list[MemoryRecord]:
        """Most recently created active memories (newest first)."""
        where = ["mi.status = 'active'"]
        params: list[Any] = []
        if pillar:
            where.append("mi.pillar = %s")
            params.append(pillar)
        where_sql = " AND ".join(where)
        sql = f"""
            SELECT mi.id, mi.pillar, mi.kind, mi.content, mi.subject, mi.tags,
                   mi.scope, mi.scope_ref_id, mi.visibility, mi.source, mi.confidence,
                   mi.importance, mi.version, mi.status, mi.created_at, a.name AS agent,
                   NULL AS score
            FROM memory_items mi
            LEFT JOIN agents a ON a.id = mi.owner_id AND mi.owner_type = 'agent'
            WHERE {where_sql}
            ORDER BY mi.created_at DESC
            LIMIT %s
        """
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(sql, [*params, limit])
            rows = await cur.fetchall()
        return [_row_to_record(r, org_id, score_is_distance=False) for r in rows]

    async def list_subjects(
        self, org_id: UUID, *, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Distinct semantic subjects with their item count and last update.

        Powers the wiki topic index: one knowledge-base page per ``subject``.
        """
        sql = """
            SELECT mi.subject, COUNT(*) AS n, MAX(mi.created_at) AS updated_at
            FROM memory_items mi
            WHERE mi.status = 'active' AND mi.pillar = 'semantic'
              AND mi.subject IS NOT NULL AND mi.subject <> ''
            GROUP BY mi.subject
            ORDER BY updated_at DESC
            LIMIT %s
        """
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(sql, (limit,))
            rows = await cur.fetchall()
        return [
            {"subject": r[0], "count": int(r[1]), "updated_at": r[2]}
            for r in rows
        ]

    async def list_by_subject(
        self, org_id: UUID, subject: str, *, limit: int = 200
    ) -> list[MemoryRecord]:
        """Active semantic records for one subject, newest first (wiki topic page)."""
        sql = """
            SELECT mi.id, mi.pillar, mi.kind, mi.content, mi.subject, mi.tags,
                   mi.scope, mi.scope_ref_id, mi.visibility, mi.source, mi.confidence,
                   mi.importance, mi.version, mi.status, mi.created_at, a.name AS agent,
                   NULL AS score
            FROM memory_items mi
            LEFT JOIN agents a ON a.id = mi.owner_id AND mi.owner_type = 'agent'
            WHERE mi.status = 'active' AND mi.pillar = 'semantic' AND mi.subject = %s
            ORDER BY mi.created_at DESC
            LIMIT %s
        """
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(sql, (subject, limit))
            rows = await cur.fetchall()
        return [_row_to_record(r, org_id, score_is_distance=False) for r in rows]


def _row_to_record(row: tuple[Any, ...], org_id: UUID, *, score_is_distance: bool = True) -> MemoryRecord:
    raw = row[16]
    score = (1.0 - float(raw)) if (score_is_distance and raw is not None) else (
        float(raw) if raw is not None else None
    )
    pillar = row[1]
    return MemoryRecord(
        id=str(row[0]),
        pillar=pillar if pillar in {"semantic", "episodic"} else "semantic",
        kind=row[2],
        content=row[3],
        subject=row[4],
        tags=list(row[5] or []),
        score=score,
        created_at=row[14],
        agent=row[15],
        org_id=org_id,
        scope=row[6],
        scope_ref_id=row[7],
        visibility=row[8],
        source=row[9],
        confidence=row[10],
        importance=row[11],
        version=row[12],
        status=row[13],
    )


def _row_to_item(row: tuple[Any, ...]) -> MemoryItem:
    return MemoryItem(
        id=row[0], org_id=row[1], pillar=row[2], kind=row[3], scope=row[4],
        scope_ref_id=row[5], visibility=row[6], content=row[7], summary=row[8],
        subject=row[9], tags=list(row[10] or []), source=row[11], source_ref=row[12],
        confidence=row[13], importance=row[14], owner_type=row[15], owner_id=row[16],
        creator_type=row[17], creator_id=row[18], status=row[19], version=row[20],
        content_hash=row[21], expires_at=row[22], created_at=row[23],
    )
