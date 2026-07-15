"""Connector interface shared by every adapter.

A connector knows how to fetch documents from an external system, incrementally
(via an opaque cursor), and to surface each document's source permissions (ACL)
so the importer can mirror them onto the resulting memory's scope/visibility.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceDoc:
    external_id: str
    content: str
    uri: str | None = None
    title: str | None = None
    acl: dict[str, Any] = field(default_factory=dict)   # mirrored source permissions
    metadata: dict[str, Any] = field(default_factory=dict)
    deleted: bool = False


@dataclass
class SyncResult:
    documents: list[SourceDoc]
    next_cursor: str | None
    has_more: bool = False


class Connector(abc.ABC):
    """Adapter base. ``kind`` matches the ``connectors.kind`` column."""

    kind: str = "base"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    @abc.abstractmethod
    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        """Fetch a page of documents since ``cursor`` using the decrypted token."""
        raise NotImplementedError

    def default_scope(self) -> str:
        """Where imported docs land by default (overridable per connector)."""
        return str(self.config.get("scope", "org"))

    # --- bidirectional (read/search/send) hooks ---------------------------
    # Only some adapters (Gmail, Slack) implement these; the base raises so a
    # misconfigured call fails loudly rather than silently no-op'ing.

    async def list_messages(
        self, token: str, query: str, *, max_results: int = 10
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(f"{self.kind} does not support list_messages")

    async def get_message(self, token: str, message_id: str) -> dict[str, Any]:
        raise NotImplementedError(f"{self.kind} does not support get_message")

    async def send(
        self, token: str, *, to: str, subject: str, body: str, thread_id: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(f"{self.kind} does not support send")

    async def post_message(
        self, token: str, channel: str, text: str, *, thread_ts: str | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError(f"{self.kind} does not support post_message")

    async def list_thread_replies(
        self, token: str, channel: str, thread_ts: str
    ) -> list[dict[str, Any]]:
        raise NotImplementedError(f"{self.kind} does not support list_thread_replies")
