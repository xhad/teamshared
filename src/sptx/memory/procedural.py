"""Postgres-backed procedural memory: agent-callable skills/recipes.

Procedures are markdown-first so an agent can read ``steps_md`` and execute
them by hand if the optional ``tool_recipe`` JSON doesn't cover its situation.
Versioning is monotonic per name; ``get`` always returns the latest unless
asked for a specific version.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from psycopg_pool import AsyncConnectionPool

from sptx.logging import get_logger
from sptx.memory.types import MemoryRecord

log = get_logger(__name__)


class ProceduralStore:
    """CRUD over the ``procedures`` table (defined in ``infra/migrations/001_init.sql``)."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = AsyncConnectionPool(conninfo=self._dsn, min_size=1, max_size=4, open=False)
        await self._pool.open()
        log.info("procedural_store_connected", dsn=self._dsn.split("@")[-1])

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("ProceduralStore not connected; call connect() first")
        return self._pool

    async def set_procedure(
        self,
        name: str,
        steps_md: str,
        *,
        agent: str,
        tool_recipe: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Insert a new version of a procedure. Returns the stored row as a dict."""
        recipe_json = json.dumps(tool_recipe) if tool_recipe is not None else None
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COALESCE(MAX(version), 0) + 1 AS next_version
                FROM procedures
                WHERE name = %s
                """,
                (name,),
            )
            row = await cur.fetchone()
            next_version = int(row[0]) if row else 1
            await cur.execute(
                """
                INSERT INTO procedures
                    (name, version, description, steps_md, tool_recipe, tags, created_by, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                RETURNING id, name, version, description, steps_md, tool_recipe, tags,
                          created_by, created_at
                """,
                (
                    name,
                    next_version,
                    description,
                    steps_md,
                    recipe_json,
                    tags or [],
                    agent,
                    datetime.now(UTC),
                ),
            )
            inserted = await cur.fetchone()
            await conn.commit()

        if inserted is None:
            raise RuntimeError("INSERT did not return a row")
        return _row_to_dict(inserted)

    async def get_procedure(
        self,
        name: str,
        version: int | None = None,
    ) -> dict[str, Any] | None:
        async with self.pool.connection() as conn, conn.cursor() as cur:
            if version is None:
                await cur.execute(
                    """
                    SELECT id, name, version, description, steps_md, tool_recipe, tags,
                           created_by, created_at
                    FROM procedures
                    WHERE name = %s
                    ORDER BY version DESC
                    LIMIT 1
                    """,
                    (name,),
                )
            else:
                await cur.execute(
                    """
                    SELECT id, name, version, description, steps_md, tool_recipe, tags,
                           created_by, created_at
                    FROM procedures
                    WHERE name = %s AND version = %s
                    """,
                    (name, version),
                )
            row = await cur.fetchone()
            return _row_to_dict(row) if row else None

    async def list_procedures(
        self,
        *,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the latest version of every procedure (optionally filtered by tag)."""
        async with self.pool.connection() as conn, conn.cursor() as cur:
            if tag:
                await cur.execute(
                    """
                    SELECT DISTINCT ON (name)
                        id, name, version, description, steps_md, tool_recipe, tags,
                        created_by, created_at
                    FROM procedures
                    WHERE %s = ANY(tags)
                    ORDER BY name, version DESC
                    LIMIT %s
                    """,
                    (tag, limit),
                )
            else:
                await cur.execute(
                    """
                    SELECT DISTINCT ON (name)
                        id, name, version, description, steps_md, tool_recipe, tags,
                        created_by, created_at
                    FROM procedures
                    ORDER BY name, version DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            rows = await cur.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def search_procedures(self, query: str, limit: int = 10) -> list[MemoryRecord]:
        """Lexical search via Postgres trigram + full-text on ``name``/``description``/``steps_md``.

        We don't put procedures into Mem0 because they aren't conversational
        memories; they're versioned artifacts the agent reads verbatim.
        """
        async with self.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute(
                """
                SELECT DISTINCT ON (name)
                    id, name, version, description, steps_md, tool_recipe, tags,
                    created_by, created_at,
                    ts_rank(
                        to_tsvector('english',
                            coalesce(name,'') || ' ' || coalesce(description,'') || ' ' || coalesce(steps_md,'')),
                        plainto_tsquery('english', %s)
                    ) AS rank
                FROM procedures
                WHERE to_tsvector('english',
                        coalesce(name,'') || ' ' || coalesce(description,'') || ' ' || coalesce(steps_md,''))
                      @@ plainto_tsquery('english', %s)
                ORDER BY name, version DESC, rank DESC
                LIMIT %s
                """,
                (query, query, limit),
            )
            rows = await cur.fetchall()

        records: list[MemoryRecord] = []
        for row in rows:
            d = _row_to_dict(row[:-1])
            records.append(
                MemoryRecord(
                    id=str(d["id"]),
                    pillar="procedural",
                    kind="procedure",
                    content=f"{d['name']} (v{d['version']}): {d.get('description') or d['steps_md'][:200]}",
                    agent=d.get("created_by"),
                    tags=list(d.get("tags") or []),
                    score=float(row[-1]) if row[-1] is not None else None,
                    created_at=d.get("created_at"),
                    metadata={
                        "name": d["name"],
                        "version": d["version"],
                        "tool_recipe": d.get("tool_recipe"),
                    },
                )
            )
        return records


def _row_to_dict(row: tuple[Any, ...] | None) -> dict[str, Any]:
    if row is None:
        return {}
    fields = (
        "id",
        "name",
        "version",
        "description",
        "steps_md",
        "tool_recipe",
        "tags",
        "created_by",
        "created_at",
    )
    return dict(zip(fields, row, strict=False))
