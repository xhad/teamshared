"""Postgres-backed graph store (Neo4j-free fallback).

Uses ``memory_graph_edges`` so autolink and graph traversal work without an
optional Neo4j deployment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord
from teamshared.tenancy.context import TenantDb

if TYPE_CHECKING:
    pass

log = get_logger(__name__)


class PostgresGraphStore:
    """Org-scoped entity graph in Postgres."""

    def __init__(self, tenant_db: TenantDb) -> None:
        self._db = tenant_db

    async def connect(self) -> None:
        await self._db.connect()
        log.info("postgres_graph_store_ready")

    async def close(self) -> None:
        """No-op — shares the process-wide ``TenantDb`` pool."""

    async def verify(self) -> None:
        async with self._db.admin() as conn:
            cur = await conn.execute("SELECT 1")
            await cur.fetchone()

    async def add_relation(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        org_id: str,
        agent: str,
        weight: float = 1.0,
    ) -> None:
        oid = UUID(org_id)
        async with self._db.org(oid) as conn:
            await conn.execute(
                """
                INSERT INTO memory_graph_edges
                    (org_id, subject, predicate, object, weight, created_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (org_id, subject, predicate, object)
                DO UPDATE SET weight = memory_graph_edges.weight + EXCLUDED.weight
                """,
                (org_id, subject, predicate, object_, weight, agent),
            )

    async def related(
        self, name: str, *, org_id: str, depth: int = 2, limit: int = 20
    ) -> list[MemoryRecord]:
        """Return entities related to ``name`` within ``org_id`` (1-hop for v1)."""
        oid = UUID(org_id)
        async with self._db.org(oid) as conn:
            cur = await conn.execute(
                """
                SELECT object AS name, predicate, 1 AS hops
                FROM memory_graph_edges
                WHERE org_id = %s AND lower(subject) = lower(%s)
                UNION ALL
                SELECT subject AS name, predicate, 1 AS hops
                FROM memory_graph_edges
                WHERE org_id = %s AND lower(object) = lower(%s)
                LIMIT %s
                """,
                (org_id, name, org_id, name, limit),
            )
            rows = await cur.fetchall()

        return [
            MemoryRecord(
                id=f"graph:{r[0]}",
                pillar="semantic",
                content=f"{name} --[{r[1]}]--> {r[0]}",
                subject=r[0],
                metadata={"hops": r[2], "predicates": [r[1]]},
                score=1.0,
            )
            for r in rows
        ]

    async def neighbors_for_boost(
        self, org_id: str, names: list[str], *, limit: int = 10
    ) -> set[str]:
        """Entity names one hop from any of ``names`` — used for retrieval boost."""
        if not names:
            return set()
        oid = UUID(org_id)
        found: set[str] = set()
        async with self._db.org(oid) as conn:
            for name in names[:5]:
                cur = await conn.execute(
                    """
                    SELECT object FROM memory_graph_edges
                    WHERE org_id = %s AND lower(subject) = lower(%s)
                    UNION
                    SELECT subject FROM memory_graph_edges
                    WHERE org_id = %s AND lower(object) = lower(%s)
                    LIMIT %s
                    """,
                    (org_id, name, org_id, name, limit),
                )
                for row in await cur.fetchall():
                    found.add(str(row[0]).lower())
        return found
