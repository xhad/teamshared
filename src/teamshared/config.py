"""Typed runtime configuration loaded from env (and optional .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse
from uuid import UUID

DEFAULT_ORG_ID = UUID("00000000-0000-0000-0000-000000000001")

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

EmbedProvider = Literal["openai", "ollama"]
LLMProvider = Literal["openai", "ollama"]
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
    legacy_token_mint_enabled: bool = Field(
        default=False,
        description=(
            "Allow TokenStore.mint (legacy teamshared_* file tokens). Disabled in "
            "production; use AgentTokenMinter / invite redeem for tsk_ keys."
        ),
    )
    legacy_token_auth_enabled: bool = Field(
        default=False,
        description=(
            "Accept teamshared_* tokens from tokens_file in BearerAuthMiddleware. "
            "Off by default; enable only during migration. tsk_ API keys always work."
        ),
    )
    tokens_file: Path = Field(default=Path("./.teamshared/tokens.json"))
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
    otp_ttl_seconds: int = Field(
        default=30,
        description=(
            "Lifetime of a console sign-in one-time passcode (OTP). Kept short; the "
            "code is single-use and capped by otp_max_attempts."
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

    embed_provider: EmbedProvider = "openai"
    embed_model: str = "text-embedding-3-small"
    embed_dims: int = 1536

    llm_provider: LLMProvider = "openai"
    llm_model: str = "gpt-4o-mini"

    ollama_base_url: str = "http://localhost:11434"

    neo4j_url: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    distill_interval_seconds: int = 30

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
