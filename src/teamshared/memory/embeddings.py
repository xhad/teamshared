"""Embedding generation, decoupled from any single vector backend.

Three implementations:

* :class:`OpenAIEmbedder` -- production default.
* :class:`OllamaEmbedder` -- self-hosted models.
* :class:`HashEmbedder` -- deterministic, offline, dependency-free. Used by
  tests and air-gapped dev so the memory layer is exercisable without an API
  key. It is NOT semantically meaningful; never use it in production.

All produce vectors of ``settings.embed_dims`` (default 1536) so they drop
straight into the ``vector(1536)`` column.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Protocol

import httpx
from openai import AsyncOpenAI

from teamshared.config import Settings
from teamshared.logging import get_logger
from teamshared.metrics import METRICS

log = get_logger(__name__)


class Embedder(Protocol):
    dims: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic pseudo-embeddings from SHA-256. Offline + reproducible."""

    def __init__(self, dims: int = 1536) -> None:
        self.dims = dims

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec: list[float] = []
        counter = 0
        while len(vec) < self.dims:
            digest = hashlib.sha256(f"{counter}:{text}".encode()).digest()
            for i in range(0, len(digest), 4):
                if len(vec) >= self.dims:
                    break
                chunk = int.from_bytes(digest[i : i + 4], "big")
                vec.append((chunk / 2**32) * 2.0 - 1.0)
            counter += 1
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class OpenAIEmbedder:
    def __init__(self, model: str, dims: int, api_key: str | None = None) -> None:
        self.model = model
        self.dims = dims
        self._api_key = api_key

    async def embed(self, texts: list[str]) -> list[list[float]]:
        client = AsyncOpenAI(api_key=self._api_key) if self._api_key else AsyncOpenAI()
        resp = await client.embeddings.create(model=self.model, input=texts)
        METRICS.embed_calls.inc(provider="openai")
        METRICS.embed_texts.inc(len(texts), provider="openai")
        return [d.embedding for d in resp.data]


class OllamaEmbedder:
    def __init__(self, model: str, dims: int, base_url: str) -> None:
        self.model = model
        self.dims = dims
        self.base_url = base_url.rstrip("/")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                resp = await client.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                resp.raise_for_status()
                out.append(resp.json()["embedding"])
        METRICS.embed_calls.inc(provider="ollama")
        METRICS.embed_texts.inc(len(texts), provider="ollama")
        return out


def build_embedder(settings: Settings, *, allow_hash_fallback: bool = True) -> Embedder:
    """Pick an embedder from settings, falling back to :class:`HashEmbedder`.

    The fallback triggers for the OpenAI provider when no API key is present
    so local/test runs do not hard-fail. Production should always have a key.
    """
    if settings.embed_provider == "ollama":
        return OllamaEmbedder(settings.embed_model, settings.embed_dims, settings.ollama_base_url)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key and allow_hash_fallback:
        log.warning("embedder_hash_fallback", reason="no OPENAI_API_KEY; using HashEmbedder")
        return HashEmbedder(settings.embed_dims)
    return OpenAIEmbedder(settings.embed_model, settings.embed_dims, api_key)
