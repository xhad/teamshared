"""LocalEmbedder (in-process ONNX) unit tests + build_embedder selection."""

from __future__ import annotations

from typing import Any

import pytest

import teamshared.memory.embeddings as embeddings_mod
from teamshared.config import Settings
from teamshared.memory.embeddings import HashEmbedder, LocalEmbedder, build_embedder


class FakeEngine:
    """Stands in for fastembed.TextEmbedding: returns fixed-dim raw vectors."""

    def __init__(self, dims: int = 4) -> None:
        self.dims = dims
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t))] * self.dims for t in texts]


async def test_local_embedder_pads_to_target_dims() -> None:
    engine = FakeEngine(dims=4)
    emb = LocalEmbedder("fake-model", dims=8, _engine=engine)
    [vec] = await emb.embed(["hi"])
    assert len(vec) == 8
    assert vec[:4] == [2.0, 2.0, 2.0, 2.0]
    assert vec[4:] == [0.0, 0.0, 0.0, 0.0]
    assert engine.calls == [["hi"]]


async def test_local_embedder_rejects_oversized_model() -> None:
    emb = LocalEmbedder("fake-model", dims=2, _engine=FakeEngine(dims=4))
    with pytest.raises(ValueError, match="exceeding"):
        await emb.embed(["hi"])


def test_local_embedder_model_tag_distinguishes_rows() -> None:
    emb = LocalEmbedder("BAAI/bge-small-en-v1.5", dims=1536, _engine=FakeEngine())
    assert emb.model == "local:BAAI/bge-small-en-v1.5"
    assert emb.dims == 1536


def test_build_embedder_local_selects_local(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeTextEmbedding:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

    monkeypatch.setattr(embeddings_mod, "TextEmbedding", FakeTextEmbedding)
    settings = Settings(
        embed_provider="local",
        embed_local_model="some/model",
        embed_dims=16,
        embed_cache_dir="/tmp/models",
    )
    emb = build_embedder(settings)
    assert isinstance(emb, LocalEmbedder)
    assert emb.model == "local:some/model"
    assert emb.dims == 16
    assert emb._engine.kwargs == {"model_name": "some/model", "cache_dir": "/tmp/models"}


def test_build_embedder_local_without_fastembed_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings_mod, "TextEmbedding", None)
    settings = Settings(embed_provider="local", embed_dims=32)
    emb = build_embedder(settings)
    assert isinstance(emb, HashEmbedder)
    assert emb.dims == 32
    with pytest.raises(RuntimeError, match="local-embed"):
        build_embedder(settings, allow_hash_fallback=False)
