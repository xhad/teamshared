"""Maps connector ``kind`` strings to adapter classes."""

from __future__ import annotations

from typing import Any

from teamshared.connectors.adapters import (
    DiscordConnector,
    GitHubConnector,
    GmailConnector,
    GoogleDriveConnector,
    LinearConnector,
    MCPConnector,
    NotionConnector,
    SlackConnector,
)
from teamshared.connectors.base import Connector

_REGISTRY: dict[str, type[Connector]] = {
    GitHubConnector.kind: GitHubConnector,
    SlackConnector.kind: SlackConnector,
    DiscordConnector.kind: DiscordConnector,
    NotionConnector.kind: NotionConnector,
    GoogleDriveConnector.kind: GoogleDriveConnector,
    LinearConnector.kind: LinearConnector,
    MCPConnector.kind: MCPConnector,
    GmailConnector.kind: GmailConnector,
}

CONNECTOR_KINDS = tuple(_REGISTRY)


def build_connector(kind: str, config: dict[str, Any]) -> Connector:
    cls = _REGISTRY.get(kind)
    if cls is None:
        raise ValueError(f"unknown connector kind: {kind!r} (known: {', '.join(CONNECTOR_KINDS)})")
    return cls(config)
