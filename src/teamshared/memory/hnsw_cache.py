"""In-memory per-org HNSW candidate cache in front of pgvector.

The cache is a *candidate generator*, not a source of truth: it holds only
``(memory_id, vector)`` pairs for active memories embedded with the active
model, partitioned strictly by ``org_id``. A recall query runs ANN search here
(microseconds) and the resulting candidate ids are re-filtered and hydrated by
``VectorStore`` through the normal RLS + scope-filter SQL, so authorization is
never decided in process memory.

Lifecycle:

* **Hydrate** lazily per org on first search (one streaming query under
  ``db.org(org_id)``); a per-org asyncio lock prevents duplicate hydration.
* **Write-through** on ``VectorStore.add`` / ``update_content``; removals on
  soft-delete / non-active status.
* **Invalidate** (drop + rehydrate) when a memory is re-activated or the
  embedder model changes.

hnswlib is an optional extra (``teamshared[hnsw]``). When missing -- or when
``TEAMSHARED_HNSW_CACHE_ENABLED=false`` -- every call degrades to "cache
unavailable" and ``VectorStore`` keeps using the pgvector SQL path.
"""

from __future__ import annotations

import asyncio
import threading

from teamshared.logging import get_logger
from teamshared.tenancy.context import TenantDb

try:  # Optional extra: pip install 'teamshared[hnsw]'
    import hnswlib
    import numpy as np
except ImportError:  # pragma: no cover - exercised via `available`
    hnswlib = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]

log = get_logger(__name__)

_INITIAL_CAPACITY = 1024


def parse_vector_text(text: str) -> list[float]:
    """Parse pgvector's ``[x,y,...]`` text representation."""
    return [float(p) for p in text.strip("[]").split(",") if p]


class _OrgIndex:
    """One hnswlib index plus label bookkeeping, guarded by a thread lock."""

    def __init__(self, dims: int) -> None:
        self.dims = dims
        self.index = hnswlib.Index(space="cosine", dim=dims)
        self.index.init_index(
            max_elements=_INITIAL_CAPACITY, ef_construction=200, M=16
        )
        self.index.set_ef(128)
        self.next_label = 0
        self.label_to_memory: dict[int, str] = {}
        self.memory_to_labels: dict[str, list[int]] = {}
        self.active = 0
        self.lock = threading.Lock()

    def add(self, memory_id: str, vector: list[float]) -> None:
        with self.lock:
            self._remove_locked(memory_id)
            if self.next_label >= self.index.get_max_elements():
                self.index.resize_index(self.index.get_max_elements() * 2)
            label = self.next_label
            self.next_label += 1
            self.index.add_items(
                np.asarray([vector], dtype=np.float32), np.asarray([label])
            )
            self.label_to_memory[label] = memory_id
            self.memory_to_labels.setdefault(memory_id, []).append(label)
            self.active += 1

    def remove(self, memory_id: str) -> None:
        with self.lock:
            self._remove_locked(memory_id)

    def _remove_locked(self, memory_id: str) -> None:
        for label in self.memory_to_labels.pop(memory_id, []):
            self.index.mark_deleted(label)
            self.label_to_memory.pop(label, None)
            self.active -= 1

    def search(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        with self.lock:
            if self.active <= 0:
                return []
            n = min(k, self.active)
            labels, distances = self.index.knn_query(
                np.asarray([vector], dtype=np.float32), k=n
            )
        out: list[tuple[str, float]] = []
        for label, dist in zip(labels[0], distances[0], strict=True):
            memory_id = self.label_to_memory.get(int(label))
            if memory_id is not None:
                out.append((memory_id, float(dist)))
        return out


class HnswCache:
    def __init__(self, dims: int, *, enabled: bool = True) -> None:
        self.dims = dims
        self.enabled = enabled
        self._orgs: dict[str, _OrgIndex] = {}
        self._models: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def available(self) -> bool:
        return self.enabled and hnswlib is not None

    def is_hydrated(self, org_id: str) -> bool:
        return org_id in self._orgs

    async def ensure_hydrated(self, org_id: str, db: TenantDb, model: str) -> None:
        """Hydrate the org's index from Postgres if needed (idempotent)."""
        if not self.available:
            return
        if self._models.get(org_id) not in (None, model):
            self.invalidate(org_id)
        if org_id in self._orgs:
            return
        lock = self._locks.setdefault(org_id, asyncio.Lock())
        async with lock:
            if org_id in self._orgs:
                return
            index = _OrgIndex(self.dims)
            async with db.org(org_id) as conn:
                cur = await conn.execute(
                    """
                    SELECT mc.memory_id, me.embedding::text
                    FROM memory_embeddings me
                    JOIN memory_chunks mc ON mc.id = me.chunk_id
                    JOIN memory_items mi ON mi.id = mc.memory_id
                    WHERE mi.status = 'active' AND me.model = %s
                    """,
                    (model,),
                )
                rows = await cur.fetchall()
            for memory_id, embedding_text in rows:
                index.add(str(memory_id), parse_vector_text(embedding_text))
            self._orgs[org_id] = index
            self._models[org_id] = model
            log.info("hnsw_cache_hydrated", org_id=org_id, model=model, items=len(rows))

    def add(self, org_id: str, memory_id: str, vector: list[float]) -> None:
        """Write-through insert/replace; no-op for orgs not yet hydrated."""
        index = self._orgs.get(org_id)
        if index is not None:
            index.add(memory_id, vector)

    def remove(self, org_id: str, memory_id: str) -> None:
        index = self._orgs.get(org_id)
        if index is not None:
            index.remove(memory_id)

    def invalidate(self, org_id: str) -> None:
        """Drop the org's index; the next search rehydrates from Postgres."""
        self._orgs.pop(org_id, None)
        self._models.pop(org_id, None)

    def search(self, org_id: str, vector: list[float], k: int) -> list[tuple[str, float]] | None:
        """ANN candidates ``(memory_id, cosine_distance)`` or None if unavailable."""
        if not self.available:
            return None
        index = self._orgs.get(org_id)
        if index is None:
            return None
        return index.search(vector, k)
