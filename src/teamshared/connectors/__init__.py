"""Connector framework: ingest external systems into tenant-scoped memory.

Each connector kind (Slack, GitHub, Notion, Google Drive, Linear, MCP) is an
adapter that fetches documents incrementally, mirrors source permissions, and
hands content to the ingestion pipeline (as ``source='connector'``, so it lands
in the approval queue by default). OAuth tokens are encrypted at rest by
:class:`~teamshared.connectors.vault.TokenVault`.
"""

from teamshared.connectors.base import Connector, SourceDoc, SyncResult
from teamshared.connectors.oauth import (
    DISCORD_SCOPES,
    GMAIL_SCOPES,
    OAuthExchangeResult,
    SLACK_SCOPES,
    build_authorize_url,
    exchange_code,
    refresh_access_token,
    revoke_token,
)
from teamshared.connectors.registry import CONNECTOR_KINDS, build_connector
from teamshared.connectors.service import ConnectorService
from teamshared.connectors.vault import TokenBundle, TokenVault

__all__ = [
    "CONNECTOR_KINDS",
    "DISCORD_SCOPES",
    "GMAIL_SCOPES",
    "OAuthExchangeResult",
    "SLACK_SCOPES",
    "Connector",
    "ConnectorService",
    "SourceDoc",
    "SyncResult",
    "TokenBundle",
    "TokenVault",
    "build_authorize_url",
    "build_connector",
    "exchange_code",
    "refresh_access_token",
    "revoke_token",
]
