"""Mem0-backed semantic + episodic memory.

Both pillars share a single Mem0 instance (one collection in pgvector) and are
distinguished by metadata: ``pillar="semantic"`` vs ``pillar="episodic"``. We
keep them together because Mem0's extraction + dedup is the value-add and it
operates on the underlying collection.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql

from teamshared.config import Settings
from teamshared.logging import get_logger
from teamshared.memory.types import MemoryKind, MemoryRecord

log = get_logger(__name__)


def _build_mem0_config(settings: Settings) -> dict[str, Any]:
    """Translate :class:`Settings` into the dict shape ``Memory.from_config`` wants."""
    vector_store = {
        "provider": "pgvector",
        "config": {
            "user": settings.pg_user,
            "password": settings.pg_password,
            "host": settings.pg_host,
            "port": str(settings.pg_port),
            "dbname": settings.pg_db,
            "collection_name": settings.mem0_collection,
            "embedding_model_dims": settings.embed_dims,
            "hnsw": True,
            "diskann": False,
        },
    }

    if settings.embed_provider == "openai":
        embedder = {
            "provider": "openai",
            "config": {"model": settings.embed_model},
        }
    else:
        embedder = {
            "provider": "ollama",
            "config": {
                "model": settings.embed_model,
                "ollama_base_url": settings.ollama_base_url,
            },
        }

    if settings.llm_provider == "openai":
        llm = {
            "provider": "openai",
            "config": {"model": settings.llm_model, "temperature": 0.1},
        }
    else:
        llm = {
            "provider": "ollama",
            "config": {
                "model": settings.llm_model,
                "ollama_base_url": settings.ollama_base_url,
                "temperature": 0.1,
            },
        }

    return {
        "vector_store": vector_store,
        "embedder": embedder,
        "llm": llm,
    }


class SemanticEpisodicStore:
    """Thin async wrapper around Mem0.

    Mem0's Python client is synchronous; we offload its calls to a thread pool
    so they don't block the event loop.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._memory: Any | None = None  # mem0.Memory once initialized

    async def connect(self) -> None:
        if self._memory is not None:
            return
        from mem0 import Memory

        cfg = _build_mem0_config(self._settings)
        loop = asyncio.get_running_loop()
        self._memory = await loop.run_in_executor(None, lambda: Memory.from_config(cfg))
        log.info(
            "mem0_connected",
            collection=self._settings.mem0_collection,
            embed_provider=self._settings.embed_provider,
            llm_provider=self._settings.llm_provider,
        )

    async def close(self) -> None:
        self._memory = None

    @property
    def is_ready(self) -> bool:
        return self._memory is not None

    async def ensure_connected(self) -> None:
        if self._memory is None:
            await self.connect()

    @property
    def memory(self) -> Any:
        if self._memory is None:
            raise RuntimeError("SemanticEpisodicStore not connected; call connect() first")
        return self._memory

    async def add(
        self,
        content: str,
        *,
        agent: str,
        pillar: str,
        kind: MemoryKind,
        subject: str | None = None,
        tags: list[str] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Add a memory.

        ``pillar`` must be ``"semantic"`` or ``"episodic"``. Mem0 will run its
        extraction pipeline against ``content`` and may produce 0..N stored
        memories; we return the raw Mem0 result list.
        """
        await self.ensure_connected()
        metadata: dict[str, Any] = {
            "pillar": pillar,
            "kind": kind,
            "agent": agent,
            "created_at": datetime.now(UTC).isoformat(),
        }
        if subject:
            metadata["subject"] = subject
        if tags:
            metadata["tags"] = tags
        if extra_metadata:
            metadata.update(extra_metadata)

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self.memory.add(
                messages=content,
                user_id=agent,
                metadata=metadata,
            ),
        )
        return self._normalize_add_result(result)

    async def search(
        self,
        query: str,
        *,
        agent: str | None = None,
        pillar: str | None = None,
        limit: int = 8,
        time_range: tuple[datetime | None, datetime | None] | None = None,
    ) -> list[MemoryRecord]:
        """Vector-search Mem0 and convert results to :class:`MemoryRecord`.

        Mem0 2.0's :meth:`Memory.search` has a hybrid scoring bug with the
        pgvector backend: ``pgvector.search`` returns cosine *distance* in the
        ``score`` field (smaller is better), but Mem0's ``score_and_rank``
        treats it as similarity (filters ``score < threshold`` and sorts DESC).
        The net effect is that the best matches get filtered out and the worst
        matches rank highest.

        Workaround: ask Mem0 for ``threshold=0`` (disables the broken filter)
        and over-fetch (``top_k = max(limit * 10, 50)``) so all candidates come
        back. :func:`_distance_to_similarity` then flips ``1 - distance`` at the
        boundary and :meth:`Recall._rerank` sorts DESC correctly, truncating to
        the caller's requested ``limit``. Remove this workaround once Mem0
        either ships per-backend score normalization or pgvector starts
        returning similarity.

        Mem0 2.0 also requires at least one entity id (``user_id``, ``agent_id``,
        or ``run_id``) inside ``filters``. For the shared-brain read path
        (``agent=None``) we discover distinct ``user_id`` scopes in the
        collection and search them with an ``in`` filter.
        """
        await self.ensure_connected()
        entity_filters = await self._mem0_entity_filters(agent)
        if entity_filters is None:
            return []

        loop = asyncio.get_running_loop()
        filters: dict[str, Any] = dict(entity_filters)
        if pillar:
            filters["pillar"] = pillar

        kwargs: dict[str, Any] = {
            "query": query,
            "top_k": max(limit * 10, 50),
            "threshold": 0.0,
            "filters": filters,
        }

        result = await loop.run_in_executor(None, lambda: self.memory.search(**kwargs))
        return self._records_from_mem0(result, time_range=time_range)

    async def delete(self, memory_id: str) -> bool:
        await self.ensure_connected()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self.memory.delete(memory_id=memory_id))
        return True

    async def list_episodes(
        self,
        *,
        agent: str | None = None,
        topic: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
    ) -> list[MemoryRecord]:
        """List episodic memories. Mem0's filtering on metadata is limited so we
        over-fetch and filter in Python; the working set is small."""
        await self.ensure_connected()
        loop = asyncio.get_running_loop()

        entity_filters = await self._mem0_entity_filters(agent)
        if entity_filters is None:
            return []

        def _fetch() -> Any:
            kwargs: dict[str, Any] = {
                "top_k": max(limit * 4, 50),
                "filters": entity_filters,
            }
            return self.memory.get_all(**kwargs)

        raw = await loop.run_in_executor(None, _fetch)
        records = self._records_from_mem0(raw)

        def _matches(r: MemoryRecord) -> bool:
            if r.pillar != "episodic":
                return False
            if topic and topic.lower() not in (r.metadata.get("topic", "") or "").lower():
                return False
            if since and r.created_at and r.created_at < since:
                return False
            return not (until and r.created_at and r.created_at > until)

        return [r for r in records if _matches(r)][:limit]

    async def stats(self) -> dict[str, Any]:
        """Aggregate semantic + episodic counts via direct SQL on the Mem0 table.

        Mem0's ``get_all`` is capped by ``top_k`` and unreliable for totals, so
        the ``/memory`` dashboard reads counts straight from the pgvector
        ``payload`` JSONB. Returns per-pillar, per-agent (``user_id``), per-kind
        (semantic only), and top-tag breakdowns.
        """
        if not self.is_ready:
            raise RuntimeError("mem0 not ready")
        table = self._settings.mem0_collection
        dsn = self._settings.pg_dsn

        def _query() -> dict[str, Any]:
            ident = sql.Identifier(table)
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT payload->>'pillar', COUNT(*) FROM {} GROUP BY 1").format(ident)
                )
                by_pillar = {(row[0] or "semantic"): int(row[1]) for row in cur.fetchall()}

                cur.execute(
                    sql.SQL(
                        "SELECT payload->>'user_id', COUNT(*) FROM {} "
                        "WHERE payload->>'user_id' IS NOT NULL AND payload->>'user_id' != '' "
                        "GROUP BY 1 ORDER BY 2 DESC"
                    ).format(ident)
                )
                by_agent = {str(row[0]): int(row[1]) for row in cur.fetchall()}

                cur.execute(
                    sql.SQL(
                        "SELECT payload->>'kind', COUNT(*) FROM {} "
                        "WHERE payload->>'pillar' = 'semantic' AND payload->>'kind' IS NOT NULL "
                        "GROUP BY 1 ORDER BY 2 DESC"
                    ).format(ident)
                )
                by_kind = {str(row[0]): int(row[1]) for row in cur.fetchall()}

                cur.execute(
                    sql.SQL(
                        "SELECT tag, COUNT(*) FROM {}, "
                        "jsonb_array_elements_text(COALESCE(payload->'tags', '[]'::jsonb)) AS tag "
                        "GROUP BY 1 ORDER BY 2 DESC LIMIT 15"
                    ).format(ident)
                )
                tags = [(str(row[0]), int(row[1])) for row in cur.fetchall()]

            return {
                "by_pillar": by_pillar,
                "by_agent": by_agent,
                "by_kind": by_kind,
                "tags": tags,
                "semantic": int(by_pillar.get("semantic", 0)),
                "episodic": int(by_pillar.get("episodic", 0)),
                "total": sum(by_pillar.values()),
            }

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _query)

    async def list_recent(
        self,
        limit: int = 10,
        pillar: str | None = None,
    ) -> list[MemoryRecord]:
        """Return the most recently created memories (newest first) via direct SQL."""
        if not self.is_ready:
            raise RuntimeError("mem0 not ready")
        table = self._settings.mem0_collection
        dsn = self._settings.pg_dsn

        def _query() -> list[MemoryRecord]:
            ident = sql.Identifier(table)
            select = (
                "SELECT id, COALESCE(payload->>'data', payload->>'memory', payload->>'text'), "
                "payload->>'user_id', payload->>'pillar', payload->>'kind', "
                "payload->>'created_at' FROM {} "
            )
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                if pillar:
                    cur.execute(
                        sql.SQL(
                            select
                            + "WHERE payload->>'pillar' = %s "
                            "ORDER BY (payload->>'created_at')::timestamptz DESC NULLS LAST LIMIT %s"
                        ).format(ident),
                        (pillar, limit),
                    )
                else:
                    cur.execute(
                        sql.SQL(
                            select
                            + "ORDER BY (payload->>'created_at')::timestamptz DESC NULLS LAST LIMIT %s"
                        ).format(ident),
                        (limit,),
                    )
                rows = cur.fetchall()

            out: list[MemoryRecord] = []
            for rid, content, user_id, plr, kind, created in rows:
                created_at: datetime | None = None
                if created:
                    try:
                        created_at = datetime.fromisoformat(str(created))
                    except ValueError:
                        created_at = None
                out.append(
                    MemoryRecord(
                        id=str(rid),
                        pillar=plr if plr in {"semantic", "episodic"} else "semantic",
                        kind=kind if kind in {"fact", "preference", "event", "note"} else None,
                        content=content or "",
                        agent=user_id,
                        created_at=created_at,
                    )
                )
            return out

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _query)

    async def _mem0_entity_filters(self, agent: str | None) -> dict[str, Any] | None:
        """Build Mem0 entity filters for one agent or the shared-brain scope."""
        if agent:
            return {"user_id": agent}
        user_ids = await self._distinct_mem0_user_ids()
        if not user_ids:
            return None
        if len(user_ids) == 1:
            return {"user_id": user_ids[0]}
        return {"user_id": {"in": user_ids}}

    async def _distinct_mem0_user_ids(self) -> list[str]:
        """Return distinct Mem0 ``user_id`` scopes stored in the pgvector table."""
        table = self._settings.mem0_collection
        dsn = self._settings.pg_dsn

        def _query() -> list[str]:
            with psycopg.connect(dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    sql.SQL(
                        "SELECT DISTINCT payload->>'user_id' FROM {} "
                        "WHERE payload->>'user_id' IS NOT NULL "
                        "AND payload->>'user_id' != ''"
                    ).format(sql.Identifier(table))
                )
                return [str(row[0]) for row in cur.fetchall() if row[0]]

        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(None, _query)
        except Exception as exc:
            log.warning("mem0_distinct_user_ids_failed", error=str(exc))
            raise RuntimeError(f"failed to discover mem0 user scopes: {exc}") from exc

    @staticmethod
    def _normalize_add_result(result: Any) -> list[dict[str, Any]]:
        if isinstance(result, dict) and "results" in result:
            return list(result["results"])
        if isinstance(result, list):
            return result
        return [result] if result is not None else []

    @staticmethod
    def _records_from_mem0(
        result: Any,
        *,
        time_range: tuple[datetime | None, datetime | None] | None = None,
    ) -> list[MemoryRecord]:
        items: list[dict[str, Any]]
        if isinstance(result, dict) and "results" in result:
            items = list(result["results"])
        elif isinstance(result, list):
            items = result
        else:
            items = []

        since, until = (time_range or (None, None))
        out: list[MemoryRecord] = []
        for item in items:
            metadata = item.get("metadata") or {}
            created_at: datetime | None = None
            raw_ts = metadata.get("created_at") or item.get("created_at")
            if raw_ts:
                try:
                    created_at = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
                except ValueError:
                    created_at = None
            if since and created_at and created_at < since:
                continue
            if until and created_at and created_at > until:
                continue

            pillar = metadata.get("pillar", "semantic")
            out.append(
                MemoryRecord(
                    id=str(item.get("id", "")),
                    pillar=pillar if pillar in {"semantic", "episodic"} else "semantic",
                    kind=metadata.get("kind"),
                    content=item.get("memory") or item.get("text") or "",
                    agent=metadata.get("agent") or item.get("user_id"),
                    subject=metadata.get("subject"),
                    tags=list(metadata.get("tags") or []),
                    score=_distance_to_similarity(item.get("score")),
                    created_at=created_at,
                    metadata={k: v for k, v in metadata.items() if k not in {"pillar", "kind"}},
                )
            )
        return out


def _distance_to_similarity(raw: Any) -> float | None:
    """Convert Mem0's pgvector ``score`` (actually cosine distance) to similarity.

    Mem0's pgvector backend selects ``vector <=> query`` (cosine distance,
    range ``[0, 2]``) and stores it in the ``score`` field. The rest of teamshared
    expects ``score`` to be a similarity where higher = better, so we flip and
    clamp here at the boundary. Any non-numeric value passes through untouched
    so working-memory records (which have no score) stay ``None``.
    """
    if raw is None or isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return max(0.0, min(1.0, 1.0 - float(raw)))
