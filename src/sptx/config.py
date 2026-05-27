"""Typed runtime configuration loaded from env (and optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbedProvider = Literal["openai", "ollama"]
LLMProvider = Literal["openai", "ollama"]


class Settings(BaseSettings):
    """All sptx runtime configuration.

    Loaded from environment variables prefixed with ``SPTX_`` (and a few
    well-known external ones like ``OPENAI_API_KEY``). A ``.env`` file in CWD is
    picked up automatically when present.

    A couple of fields accept *unprefixed* aliases so the same image runs on
    any PaaS without a per-platform shim:

    - ``port`` reads ``PORT`` as a fallback. Railway, Render, Fly, Heroku, and
      every other PaaS that injects a port use ``$PORT``; sptx-native is
      ``SPTX_PORT``. Explicit ``SPTX_PORT`` always wins over ``PORT``.
    - ``pg_dsn_override`` reads ``SPTX_PG_DSN`` or ``DATABASE_URL`` and, when
      set, short-circuits the five-part DSN. Lets a managed Postgres provider
      drop in via one variable instead of five carefully-named ones.
    """

    model_config = SettingsConfigDict(
        env_prefix="SPTX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = "0.0.0.0"
    port: int = Field(
        default=8077,
        validation_alias=AliasChoices("SPTX_PORT", "PORT"),
    )
    log_level: str = "info"
    auth_disabled: bool = False
    tokens_file: Path = Field(default=Path("./.sptx/tokens.json"))

    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "sptx"
    pg_password: str = "sptx"
    pg_db: str = "sptx"
    pg_dsn_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SPTX_PG_DSN", "DATABASE_URL"),
        description=(
            "Full Postgres DSN; when set, supersedes the five SPTX_PG_* "
            "fields. Useful on PaaS targets that emit a ready-to-use "
            "DATABASE_URL (Railway, Render, Heroku, Fly, ...)."
        ),
    )

    redis_url: str = "redis://localhost:6379/0"
    session_ttl: int = 86400

    embed_provider: EmbedProvider = "openai"
    embed_model: str = "text-embedding-3-small"
    embed_dims: int = 1536

    llm_provider: LLMProvider = "openai"
    llm_model: str = "gpt-4o-mini"

    ollama_base_url: str = "http://localhost:11434"

    neo4j_enabled: bool = False
    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    distill_enabled: bool = True
    distill_interval_seconds: int = 30

    @model_validator(mode="after")
    def _hydrate_pg_parts_from_dsn(self) -> "Settings":
        """When ``SPTX_PG_DSN`` / ``DATABASE_URL`` is present, back-populate the
        five-part fields so downstream consumers (notably Mem0's pgvector
        backend in :mod:`sptx.memory.semantic`) see consistent values without
        forcing operators to set each part individually.

        Idempotent: if ``pg_dsn_override`` is already absent we do nothing,
        and if any individual ``SPTX_PG_*`` was *also* set explicitly the
        DSN's value still wins (the DSN is the authoritative override). If
        you need split-field control on a PaaS, just don't set the DSN.
        """
        if not self.pg_dsn_override:
            return self
        parsed = urlparse(self.pg_dsn_override)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise ValueError(
                f"SPTX_PG_DSN/DATABASE_URL must use postgres:// or "
                f"postgresql:// scheme, got {parsed.scheme!r}"
            )
        if parsed.hostname:
            self.pg_host = parsed.hostname
        if parsed.port:
            self.pg_port = parsed.port
        if parsed.username:
            self.pg_user = unquote(parsed.username)
        if parsed.password:
            self.pg_password = unquote(parsed.password)
        if parsed.path and parsed.path != "/":
            self.pg_db = parsed.path.lstrip("/")
        return self

    @property
    def pg_dsn(self) -> str:
        if self.pg_dsn_override:
            return self.pg_dsn_override
        return (
            f"postgresql://{self.pg_user}:{self.pg_password}"
            f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
        )

    @property
    def mem0_collection(self) -> str:
        return "sptx_memories"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
