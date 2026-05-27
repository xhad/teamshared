"""Sanity tests for the settings loader."""

from __future__ import annotations

import os

import pytest

from sptx.config import Settings, get_settings


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if (
            key.startswith("SPTX_")
            or key in {"PORT", "DATABASE_URL"}
        ):
            monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    s = Settings(_env_file=None)
    assert s.port == 8077
    assert s.embed_provider == "openai"
    assert s.embed_dims == 1536
    assert s.pg_dsn.startswith("postgresql://")
    assert s.mem0_collection == "sptx_memories"
    assert s.pg_dsn_override is None


def test_settings_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("SPTX_PORT", "9090")
    monkeypatch.setenv("SPTX_EMBED_PROVIDER", "ollama")
    monkeypatch.setenv("SPTX_EMBED_DIMS", "768")
    s = Settings(_env_file=None)
    assert s.port == 9090
    assert s.embed_provider == "ollama"
    assert s.embed_dims == 768


def test_settings_port_falls_back_to_unprefixed_PORT(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Railway/Render/Fly/Heroku inject ``$PORT``; sptx must honor it without
    a per-platform shim. ``SPTX_PORT`` keeps precedence when both are set so
    intentional overrides aren't silently shadowed.
    """
    _clear_env(monkeypatch)
    monkeypatch.setenv("PORT", "4242")
    s = Settings(_env_file=None)
    assert s.port == 4242


def test_settings_sptx_port_wins_over_PORT(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("PORT", "4242")
    monkeypatch.setenv("SPTX_PORT", "9090")
    s = Settings(_env_file=None)
    assert s.port == 9090


def test_settings_pg_dsn_override_hydrates_parts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Setting one DSN must populate every downstream field — Mem0's
    pgvector backend reads ``pg_user``/``pg_password``/``pg_host``/
    ``pg_port``/``pg_db`` individually, so the back-population in
    ``_hydrate_pg_parts_from_dsn`` is what makes "set DATABASE_URL and go"
    actually work.
    """
    _clear_env(monkeypatch)
    monkeypatch.setenv(
        "SPTX_PG_DSN",
        "postgresql://railway-user:s3cret@db.railway.internal:6543/sptx_prod",
    )
    s = Settings(_env_file=None)
    assert s.pg_dsn == "postgresql://railway-user:s3cret@db.railway.internal:6543/sptx_prod"
    assert s.pg_user == "railway-user"
    assert s.pg_password == "s3cret"
    assert s.pg_host == "db.railway.internal"
    assert s.pg_port == 6543
    assert s.pg_db == "sptx_prod"


def test_settings_database_url_alias_works(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL", "postgres://u:p@h:5432/d"
    )
    s = Settings(_env_file=None)
    assert s.pg_user == "u"
    assert s.pg_host == "h"
    assert s.pg_db == "d"


def test_settings_pg_dsn_url_decodes_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A managed Postgres frequently emits passwords with ``%``-encoded
    special characters. We must hand Mem0 the decoded form, otherwise it
    rejects auth.
    """
    _clear_env(monkeypatch)
    monkeypatch.setenv(
        "SPTX_PG_DSN",
        "postgresql://user%40corp:p%40ss%2Fword@h:5432/d",
    )
    s = Settings(_env_file=None)
    assert s.pg_user == "user@corp"
    assert s.pg_password == "p@ss/word"


def test_settings_rejects_non_postgres_scheme(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_env(monkeypatch)
    monkeypatch.setenv("SPTX_PG_DSN", "mysql://u:p@h:3306/d")
    with pytest.raises(ValueError, match="postgres"):
        Settings(_env_file=None)
