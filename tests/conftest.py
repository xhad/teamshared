"""Shared pytest fixtures.

Most tests use *fakes* for the memory pillars so the suite runs without
Postgres / Redis / Mem0. Integration tests live behind ``@pytest.mark.integration``
and require a running ``docker compose up -d postgres redis`` plus
``OPENAI_API_KEY``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from sptx.config import Settings, get_settings


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "integration: hits real Postgres/Redis/Mem0 (slow). Skipped by default.",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("-m") and "integration" in str(config.getoption("-m")):
        return
    skip = pytest.mark.skip(reason="integration test; pass `-m integration` to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def temp_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Settings]:
    """A fresh :class:`Settings` instance per test, isolated from the user env."""
    for key in list(os.environ):
        if key.startswith("SPTX_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SPTX_TOKENS_FILE", str(tmp_path / "tokens.json"))
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()
