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
