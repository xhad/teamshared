"""Typed runtime configuration loaded from env (and optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse
from uuid import UUID

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ORG_ID = UUID("00000000-0000-0000-0000-000000000001")

EmbedProvider = Literal["openai", "ollama", "local"]
LLMProvider = Literal["openai", "ollama", "openrouter"]
DeploymentEnv = Literal["development", "production"]


class Settings(BaseSettings):
    """All teamshared runtime configuration.

    Loaded from environment variables prefixed with ``TEAMSHARED_`` (and a few
    well-known external ones like ``OPENAI_API_KEY``). A ``.env`` file in CWD is
    picked up automatically when present.

    A couple of fields accept *unprefixed* aliases so the same image runs on
    any PaaS without a per-platform shim:

    - ``port`` reads ``PORT`` as a fallback. Railway, Render, Fly, Heroku, and
      every other PaaS that injects a port use ``$PORT``; teamshared-native is
      ``TEAMSHARED_PORT``. Explicit ``TEAMSHARED_PORT`` always wins over ``PORT``.
    - ``pg_dsn_override`` reads ``TEAMSHARED_PG_DSN`` or ``DATABASE_URL`` and, when
      set, short-circuits the five-part DSN. Lets a managed Postgres provider
      drop in via one variable instead of five carefully-named ones.
    """

    model_config = SettingsConfigDict(
        env_prefix="TEAMSHARED_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    host: str = "0.0.0.0"
    port: int = Field(
        default=8077,
        validation_alias=AliasChoices("TEAMSHARED_PORT", "PORT"),
    )
    log_level: str = "info"
    deployment_env: DeploymentEnv = Field(
        default="development",
        description=(
            "When 'production', startup runs config_validate and rejects unsafe "
            "settings (auth_disabled, missing RLS app role, etc.)."
        ),
    )
    auth_disabled: bool = False
    dashboard_public_content: bool = Field(
        default=False,
        description=(
            "When true, GET /memory includes recent memory rows (content snippets). "
            "Must stay false in production."
        ),
    )
    rate_limit_enabled: bool = Field(
        default=True,
        description="Enable Redis-backed edge rate limits (mint, OTP, MCP).",
    )
    rate_limit_mint_per_minute: int = Field(
        default=10, description="POST /tokens/mint* and /tokens/invites per client IP per minute."
    )
    rate_limit_otp_send_per_minute: int = Field(
        default=3, description="Console POST /login OTP send attempts per email per minute."
    )
    rate_limit_otp_verify_per_minute: int = Field(
        default=5, description="Console POST /login/verify attempts per email per minute."
    )
    rate_limit_mcp_per_minute: int = Field(
        default=120,
        description="MCP and bearer-scoped routes per principal per minute.",
    )
    rate_limit_v1_per_minute: int = Field(
        default=120,
        description="Authenticated /v1 REST API requests per principal per minute.",
    )
    idempotency_ttl_seconds: int = Field(
        default=600,
        description="TTL for Redis Idempotency-Key claims on /v1 mutating requests.",
    )
    export_max_items: int = Field(
        default=50_000,
        description="Max active memory_items per org export (hard cap).",
    )
    rate_limit_admin_export_per_hour: int = Field(
        default=6,
        description="Org memory export operations per principal per hour.",
    )
    rate_limit_admin_purge_per_hour: int = Field(
        default=20,
        description="Per-user memory erasure operations per principal per hour.",
    )
    queue_depth_warn_threshold: int = Field(
        default=100,
        description="Distill/curate queue depth that surfaces a warning in /health.",
    )
    queue_depth_critical_threshold: int = Field(
        default=500,
        description="Distill/curate queue depth that degrades /health and fires alerts.",
    )
    observability_poll_seconds: int = Field(
        default=30,
        description="Background interval for refreshing queue depth Prometheus gauges.",
    )
    invites_file: Path = Field(default=Path("./.teamshared/invites.json"))
    self_service_tokens: bool = Field(
        default=True,
        description="Allow POST /tokens/mint with one-time invite codes.",
    )
    public_url: str | None = Field(
        default=None,
        description=(
            "Public HTTPS origin for invite links (e.g. https://teamshared.com). "
            "Used by `teamshared token invite-create` when printing share URLs."
        ),
    )
    mint_secret: str | None = Field(
        default=None,
        description=(
            "When set, enables POST /tokens/mint for self-service token creation "
            "guarded by the X-Teamshared-Mint-Secret header."
        ),
    )
    api_admin_secret: str | None = Field(
        default=None,
        description=(
            "Bootstrap secret for POST /v1/orgs (org signup) via the "
            "X-Teamshared-Admin-Secret header. Distinct from mint_secret."
        ),
    )
    session_secret: str | None = Field(
        default=None,
        description="HMAC secret for human dashboard JWT sessions (verify_session).",
    )
    job_signing_secret: str | None = Field(
        default=None,
        description=(
            "HMAC secret for distill/curate Redis queue jobs. When set, producers "
            "sign each job and workers reject unsigned or tampered payloads."
        ),
    )
    otp_ttl_seconds: int = Field(
        default=300,
        description=(
            "Lifetime of a console sign-in one-time passcode (OTP). The code is "
            "single-use and capped by otp_max_attempts."
        ),
    )
    otp_max_attempts: int = Field(
        default=5,
        description="Max wrong OTP entries before the code is invalidated.",
    )
    smtp_host: str | None = Field(
        default=None,
        description=(
            "SMTP server host for delivering console sign-in OTP emails. When unset "
            "(and not in auth_disabled dev mode), codes are not delivered."
        ),
    )
    smtp_port: int = Field(default=587, description="SMTP server port.")
    smtp_username: str | None = Field(default=None, description="SMTP auth username.")
    smtp_password: str | None = Field(default=None, description="SMTP auth password.")
    smtp_from: str | None = Field(
        default=None,
        description="From address for console OTP emails (e.g. 'teamshared <no-reply@…>').",
    )
    smtp_starttls: bool = Field(
        default=True,
        description="Issue STARTTLS after connecting (typical for port 587).",
    )
    default_org_id: UUID = Field(
        default=DEFAULT_ORG_ID,
        description=(
            "Org that legacy bearer tokens (and the MCP tool surface) resolve "
            "into. Seeded by migration 010_default_org.sql."
        ),
    )
    dashboard_owner_email: str | None = Field(
        default=None,
        description=(
            "Email of the default-org owner who can sign into the /app "
            "console via magic link. Seeded by `teamshared provision-default-org`."
        ),
    )
    api_enabled: bool = Field(
        default=True,
        description="Mount the multi-tenant /v1 REST API. Disable to run MCP-only.",
    )
    connector_encryption_key: str | None = Field(
        default=None,
        description=(
            "Base64/hex 32-byte key for envelope-encrypting connector OAuth "
            "tokens at rest (AES-GCM). Required to use connectors in production."
        ),
    )

    # --- Gmail / Google OAuth integration ---------------------------------
    gmail_client_id: str | None = Field(
        default=None,
        description="Google OAuth client id for the Gmail integration.",
    )
    gmail_client_secret: str | None = Field(
        default=None,
        description="Google OAuth client secret for the Gmail integration.",
    )
    gmail_redirect_uri: str | None = Field(
        default=None,
        description=(
            "OAuth redirect URI registered with Google for the Gmail "
            "integration, e.g. https://teamshared.com/v1/integrations/oauth/callback."
        ),
    )

    # --- Slack OAuth integration -----------------------------------------
    slack_client_id: str | None = Field(
        default=None,
        description="Slack OAuth client id for the Slack integration.",
    )
    slack_client_secret: str | None = Field(
        default=None,
        description="Slack OAuth client secret for the Slack integration.",
    )
    slack_redirect_uri: str | None = Field(
        default=None,
        description=(
            "OAuth redirect URI registered with Slack for the Slack "
            "integration, e.g. https://teamshared.com/v1/integrations/oauth/callback."
        ),
    )
    slack_signing_secret: str | None = Field(
        default=None,
        description=(
            "Slack signing secret for verifying Slack Events API webhooks "
            "(future work; not required for v1 poll-based ingestion)."
        ),
    )

    # --- Integrations sync worker ----------------------------------------
    integrations_sync_interval_seconds: int = Field(
        default=300,
        description=(
            "How often the integrations-sync worker polls each connected "
            "Gmail/Slack connector for new messages."
        ),
    )

    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_user: str = "teamshared"
    pg_password: str = "teamshared"
    pg_db: str = "teamshared"
    pg_dsn_override: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TEAMSHARED_PG_DSN", "DATABASE_URL"),
        description=(
            "Full Postgres DSN; when set, supersedes the five TEAMSHARED_PG_* "
            "fields. Useful on PaaS targets that emit a ready-to-use "
            "DATABASE_URL (Railway, Render, Heroku, Fly, ...)."
        ),
    )

    pg_app_user: str | None = Field(
        default=None,
        description=(
            "Dedicated non-superuser role the application connects as so RLS is "
            "actually enforced (a superuser bypasses RLS). When unset, the app "
            "falls back to the admin DSN -- acceptable for local dev only."
        ),
    )
    pg_app_password: str | None = Field(default=None)

    redis_url: str = "redis://localhost:6379/0"
    session_ttl: int = 86400
    console_session_ttl: int = Field(
        default=2_592_000,  # 30 days
        description=(
            "Lifetime (seconds) of a human console JWT session cookie. Sessions "
            "are rolling: each authenticated console request re-issues the cookie "
            "with a fresh expiry, so active users stay signed in without "
            "re-entering an OTP. Distinct from session_ttl (working-memory TTL)."
        ),
    )

    embed_provider: EmbedProvider = "openai"
    embed_model: str = "text-embedding-3-small"
    embed_dims: int = 1536
    embed_local_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description=(
            "fastembed (ONNX) model used when embed_provider='local'. Native "
            "vectors are zero-padded up to embed_dims for the vector column."
        ),
    )
    embed_cache_dir: str | None = Field(
        default=None,
        description="Directory where local embedding model weights are cached.",
    )
    hnsw_cache_enabled: bool = Field(
        default=True,
        description=(
            "Serve vector recall candidates from an in-memory per-org HNSW "
            "index (hydrated from Postgres, write-through). Set false to "
            "always use the pgvector SQL path."
        ),
    )

    llm_provider: LLMProvider = "openai"
    llm_model: str = "gpt-4o-mini"

    ollama_base_url: str = "http://localhost:11434"

    openrouter_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TEAMSHARED_OPENROUTER_API_KEY", "OPENROUTER_API_KEY"),
        description=(
            "API key for OpenRouter (https://openrouter.ai). Required when "
            "llm_provider='openrouter'. Reads OPENROUTER_API_KEY as a fallback."
        ),
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        description=(
            "OpenAI-compatible base URL for OpenRouter chat completions. "
            "OpenRouter offers no embeddings endpoint, so embed_provider must "
            "stay 'openai' or 'local' when using OpenRouter for the LLM role."
        ),
    )

    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"
    autolink_enabled: bool = Field(
        default=True,
        description="Extract entity refs on memory write and create graph edges (zero LLM).",
    )
    postgres_graph_fallback: bool = Field(
        default=True,
        description="Use Postgres memory_graph_edges when Neo4j is unavailable.",
    )

    distill_interval_seconds: int = 30

    compress_min_chars: int = Field(
        default=800,
        description="Skip compression when a message block is shorter than this.",
    )
    compress_target_ratio: float = Field(
        default=0.35,
        ge=0.05,
        le=1.0,
        description="Target size as a fraction of original for plain-text truncation.",
    )
    compress_json_max_items: int = Field(
        default=20,
        ge=5,
        le=200,
        description="Max JSON array items retained after SmartCrusher-lite sampling.",
    )
    compress_log_max_lines: int = Field(
        default=40,
        ge=10,
        le=500,
        description="Max log lines retained after log compression.",
    )
    compress_ccr_ttl_seconds: int = Field(
        default=3600,
        description="TTL for Compress-Cache-Retrieve originals in Redis.",
    )

    mcp_tool_output_normalize_enabled: bool = Field(
        default=True,
        description="Strip, clean, and compress MCP tool responses before agents see them.",
    )
    mcp_tool_output_max_record_chars: int = Field(
        default=600,
        ge=100,
        le=4000,
        description="Max chars per record/content field in recall-style tool responses.",
    )

    llm_prepare_enabled: bool = Field(
        default=True,
        description=(
            "Enable context_prepare / POST /llm/prepare and internal paths: "
            "session-append user turn, inject assembled teamshared context, then compress."
        ),
    )
    llm_prepare_context_token_budget: int = Field(
        default=1500,
        description="Token budget for context assembly injected before LLM calls.",
    )
    soul_max_chars: int = Field(
        default=2400,
        description=(
            "Hard character cap for each person's private soul profile "
            "(≈600 tokens). Session-start soul blocks stay small and light."
        ),
    )

    gateway_enabled: bool = Field(
        default=False,
        description=(
            "Enable the OpenAI-compatible chat-completions gateway at "
            "/gateway/v1/chat/completions. Harnesses that support a custom "
            "base URL (e.g. OpenClaw) point their model calls here so every "
            "request gets session append + compression + context enrichment "
            "server-side before being proxied upstream."
        ),
    )
    gateway_upstream_base_url: str | None = Field(
        default=None,
        description=(
            "OpenAI-compatible base URL (ending in /v1) the gateway forwards "
            "chat completions to, e.g. https://api.openai.com/v1 or an "
            "OpenRouter/LiteLLM endpoint. Required when gateway_enabled."
        ),
    )
    gateway_upstream_api_key: str | None = Field(
        default=None,
        description="Bearer key sent to the upstream provider by the gateway.",
    )
    gateway_default_model: str | None = Field(
        default=None,
        description="Upstream model used when a gateway request omits `model`.",
    )
    gateway_upstream_timeout_seconds: int = Field(
        default=300,
        description="Read timeout for upstream chat completions (streaming responses).",
    )

    capture_enabled: bool = Field(
        default=True,
        description=(
            "Auto-record every MCP tool call into a per-agent implicit "
            "working session (harness-agnostic conversation capture)."
        ),
    )
    capture_idle_seconds: int = Field(
        default=1800,
        description=(
            "Idle gap after which the implicit capture session rolls over: "
            "the previous session is closed (and distilled) and a new one opened."
        ),
    )
    capture_max_turns: int = Field(
        default=200,
        description="Force a capture-session rollover once it reaches this many turns.",
    )
    curate_threshold: int = Field(
        default=3,
        description=(
            "Number of new facts a subject must accumulate before the curator "
            "re-synthesizes its wiki page (debounce against per-turn thrashing)."
        ),
    )

    @model_validator(mode="after")
    def _hydrate_pg_parts_from_dsn(self) -> Settings:
        """When ``TEAMSHARED_PG_DSN`` / ``DATABASE_URL`` is present, back-populate the
        five-part fields so downstream consumers (notably Mem0's pgvector
        backend in :mod:`teamshared.memory.semantic`) see consistent values without
        forcing operators to set each part individually.

        Idempotent: if ``pg_dsn_override`` is already absent we do nothing,
        and if any individual ``TEAMSHARED_PG_*`` was *also* set explicitly the
        DSN's value still wins (the DSN is the authoritative override). If
        you need split-field control on a PaaS, just don't set the DSN.
        """
        if not self.pg_dsn_override:
            return self
        parsed = urlparse(self.pg_dsn_override)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise ValueError(
                f"TEAMSHARED_PG_DSN/DATABASE_URL must use postgres:// or "
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
    def pg_app_dsn(self) -> str:
        """DSN the application uses at request time.

        Prefers the dedicated non-superuser ``pg_app_user`` so Row-Level
        Security is enforced. Falls back to the admin DSN when no app role is
        configured (local dev), where RLS still applies via ``FORCE`` unless
        the admin role is a superuser.
        """
        if self.pg_app_user:
            return (
                f"postgresql://{self.pg_app_user}:{self.pg_app_password or ''}"
                f"@{self.pg_host}:{self.pg_port}/{self.pg_db}"
            )
        return self.pg_dsn

    @property
    def mem0_collection(self) -> str:
        return "teamshared_memories"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
