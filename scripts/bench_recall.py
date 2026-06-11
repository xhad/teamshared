"""Recall hot-path micro-benchmark: embed latency + HNSW cache search latency.

Synthetic and self-contained (no Postgres/Redis needed):

* Embedding: times the configured embedder (LocalEmbedder if fastembed is
  installed and TEAMSHARED_EMBED_PROVIDER=local, otherwise whatever
  build_embedder picks -- HashEmbedder offline).
* ANN: hydrates an HnswCache org with N random vectors and times k-NN queries.

Usage:
    .venv/bin/python scripts/bench_recall.py [--items 50000] [--queries 200] [--dims 1536]
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
import uuid

from teamshared.config import get_settings
from teamshared.memory.embeddings import build_embedder
from teamshared.memory.hnsw_cache import HnswCache, hnswlib


def _pct(samples: list[float], p: float) -> float:
    return statistics.quantiles(samples, n=100)[int(p) - 1]


def _report(name: str, samples_ms: list[float]) -> None:
    print(
        f"{name:<28} p50={statistics.median(samples_ms):8.3f}ms  "
        f"p95={_pct(samples_ms, 95):8.3f}ms  n={len(samples_ms)}"
    )


async def bench_embed(queries: int) -> None:
    settings = get_settings()
    embedder = build_embedder(settings)
    name = f"embed [{getattr(embedder, 'model', 'hash')}]"
    try:
        await embedder.embed(["warmup"])
    except Exception as exc:
        print(f"{name:<28} skipped (backend unreachable: {exc.__class__.__name__})")
        return
    samples: list[float] = []
    for i in range(queries):
        t0 = time.perf_counter()
        await embedder.embed([f"how do we deploy service number {i}?"])
        samples.append((time.perf_counter() - t0) * 1000)
    _report(name, samples)


def bench_hnsw(items: int, queries: int, dims: int) -> None:
    if hnswlib is None:
        print("hnsw search                  skipped (hnswlib not installed)")
        return
    rng = random.Random(42)
    cache = HnswCache(dims)
    org = str(uuid.uuid4())
    # Hydrate directly through the per-org index (no DB in this bench).
    from teamshared.memory.hnsw_cache import _OrgIndex

    index = _OrgIndex(dims)
    for i in range(items):
        index.add(f"m{i}", [rng.uniform(-1, 1) for _ in range(dims)])
    cache._orgs[org] = index
    cache._models[org] = "bench"

    samples: list[float] = []
    for _ in range(queries):
        q = [rng.uniform(-1, 1) for _ in range(dims)]
        t0 = time.perf_counter()
        cache.search(org, q, k=64)
        samples.append((time.perf_counter() - t0) * 1000)
    _report(f"hnsw search [{items} items]", samples)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=int, default=50_000)
    parser.add_argument("--queries", type=int, default=200)
    parser.add_argument("--dims", type=int, default=1536)
    args = parser.parse_args()

    asyncio.run(bench_embed(args.queries))
    bench_hnsw(args.items, args.queries, args.dims)


if __name__ == "__main__":
    main()
