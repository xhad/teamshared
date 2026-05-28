"""Optional Neo4j-backed relationship graph.

Activated when ``TEAMSHARED_NEO4J_ENABLED=true``. The graph stores explicit
``(:Entity)-[r:RELATES]->(:Entity)`` edges that complement Mem0's vector
recall. Most agents won't need this; turn it on when you have enough
relational data (people, projects, products) that vector search starts to
miss connections.

The neo4j driver is an optional dep (``pip install '.[neo4j]'``); we import
it lazily so the base install stays slim.
"""

from __future__ import annotations

from typing import Any

from teamshared.logging import get_logger
from teamshared.memory.types import MemoryRecord

log = get_logger(__name__)


class GraphStore:
    """Thin wrapper over the neo4j async driver.

    Only call sites: ``add_relation`` (from any pillar that uncovers an
    explicit relationship) and ``related`` (used by ``memory_graph_recall``).
    """

    def __init__(self, url: str, user: str, password: str) -> None:
        self._url = url
        self._user = user
        self._password = password
        self._driver: Any | None = None

    async def connect(self) -> None:
        if self._driver is not None:
            return
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError as exc:
            raise RuntimeError(
                "neo4j extra not installed; run `pip install '.[neo4j]'`"
            ) from exc
        self._driver = AsyncGraphDatabase.driver(self._url, auth=(self._user, self._password))
        await self._ensure_constraints()
        log.info("graph_store_connected", url=self._url)

    async def close(self) -> None:
        if self._driver is not None:
            await self._driver.close()
            self._driver = None

    async def _ensure_constraints(self) -> None:
        async with self._driver.session() as session:
            await session.run(
                "CREATE CONSTRAINT entity_name IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE e.name IS UNIQUE"
            )

    async def add_relation(
        self,
        subject: str,
        predicate: str,
        object_: str,
        *,
        agent: str,
        weight: float = 1.0,
    ) -> None:
        """Upsert ``(subject)-[predicate]->(object)`` and bump its weight."""
        if self._driver is None:
            raise RuntimeError("GraphStore not connected")
        async with self._driver.session() as session:
            await session.run(
                """
                MERGE (s:Entity {name: $subject})
                MERGE (o:Entity {name: $object})
                MERGE (s)-[r:RELATES {predicate: $predicate}]->(o)
                ON CREATE SET r.weight = $weight, r.created_by = $agent
                ON MATCH  SET r.weight = coalesce(r.weight, 0) + $weight
                """,
                subject=subject,
                predicate=predicate,
                object=object_,
                agent=agent,
                weight=weight,
            )

    async def related(self, name: str, depth: int = 2, limit: int = 20) -> list[MemoryRecord]:
        """Return entities related to ``name`` up to ``depth`` hops away."""
        if self._driver is None:
            raise RuntimeError("GraphStore not connected")
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (start:Entity {name: $name})-[r:RELATES*1..$depth]-(o:Entity)
                RETURN o.name AS name, [rel in r | rel.predicate] AS predicates,
                       length(r) AS hops
                ORDER BY hops ASC
                LIMIT $limit
                """,
                name=name,
                depth=depth,
                limit=limit,
            )
            rows = [dict(record) async for record in result]

        return [
            MemoryRecord(
                id=f"graph:{r['name']}",
                pillar="semantic",
                content=f"{name} --[{' -> '.join(r['predicates'])}]--> {r['name']}",
                subject=r["name"],
                metadata={"hops": r["hops"], "predicates": r["predicates"]},
                score=1.0 / max(r["hops"], 1),
            )
            for r in rows
        ]
