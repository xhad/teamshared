"""Connector lifecycle: connect, store tokens, sync, disconnect.

Sync is incremental (persists a cursor), mirrors source permissions onto the
imported memory's visibility, and routes every document through the ingestion
pipeline as ``source='connector'`` -- so connector content is reviewed before
it can influence retrieval. Deletions in the source soft-delete the mirror.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from teamshared.connectors.base import Connector
from teamshared.connectors import oauth as oauth_mod
from teamshared.connectors.registry import build_connector
from teamshared.connectors.vault import TokenBundle, TokenVault
from teamshared.identity.rbac import Permissions
from teamshared.ingestion.pipeline import IngestionPipeline
from teamshared.logging import get_logger
from teamshared.memory.audit import AuditLog
from teamshared.memory.request_context import RequestContext
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)


@dataclass
class SyncReport:
    connector_id: UUID
    fetched: int
    imported: int
    next_cursor: str | None


class ConnectorService:
    def __init__(
        self,
        db: TenantDb,
        vault: TokenVault,
        ingestion_factory: Callable[[], IngestionPipeline],
        audit: AuditLog,
        *,
        settings: Any = None,
    ) -> None:
        self.db = db
        self.vault = vault
        self.ingestion_factory = ingestion_factory
        self.audit = audit
        self.settings = settings

    async def create(
        self, ctx: RequestContext, *, kind: str, name: str, config: dict[str, Any]
    ) -> UUID:
        await ctx.authorizer.require(ctx.principal, Permissions.CONNECTOR_MANAGE)
        build_connector(kind, config)  # validate kind early
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO connectors (org_id, kind, name, config, created_by) "
                "VALUES (%s,%s,%s,%s::jsonb,%s) RETURNING id",
                (str(ctx.org_id), kind, name, json.dumps(config), str(ctx.principal.id)),
            )
            row = await cur.fetchone()
        assert row is not None
        connector_id: UUID = row[0]
        await self.audit.record(
            agent=ctx.principal.attribution, action="connector.create", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="connector",
            target_id=str(connector_id), request_id=ctx.request_id,
            after={"kind": kind, "name": name},
        )
        return connector_id

    async def store_token(self, ctx: RequestContext, connector_id: UUID, token: str) -> None:
        await ctx.authorizer.require(ctx.principal, Permissions.CONNECTOR_MANAGE)
        ct, nonce, key_id = self.vault.encrypt(token)
        async with self.db.org(ctx.org_id) as conn:
            await conn.execute(
                "INSERT INTO connector_tokens (org_id, connector_id, ciphertext, nonce, key_id) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (connector_id) DO UPDATE SET ciphertext = EXCLUDED.ciphertext, "
                "nonce = EXCLUDED.nonce, key_id = EXCLUDED.key_id",
                (str(ctx.org_id), str(connector_id), ct, nonce, key_id),
            )
            await conn.execute(
                "UPDATE connectors SET status = 'connected', updated_at = now() WHERE id = %s",
                (str(connector_id),),
            )

    async def store_token_bundle(
        self, ctx: RequestContext, connector_id: UUID, bundle: "TokenBundle"
    ) -> None:
        """Store a full OAuth token bundle (access + refresh + expiry + scope)."""
        await ctx.authorizer.require(ctx.principal, Permissions.CONNECTOR_MANAGE)
        await self._persist_token_bundle(ctx, connector_id, bundle)

    async def _persist_token_bundle(
        self, ctx: RequestContext, connector_id: UUID, bundle: "TokenBundle"
    ) -> None:
        """Persist a token bundle with no RBAC check (caller already authorized)."""
        ct, nonce, key_id = self.vault.encrypt_bundle(bundle)
        async with self.db.org(ctx.org_id) as conn:
            await conn.execute(
                "INSERT INTO connector_tokens "
                "(org_id, connector_id, ciphertext, nonce, key_id, "
                " refresh_token, access_token_expires_at, token_type, scope) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (connector_id) DO UPDATE SET "
                "ciphertext = EXCLUDED.ciphertext, nonce = EXCLUDED.nonce, "
                "key_id = EXCLUDED.key_id, refresh_token = EXCLUDED.refresh_token, "
                "access_token_expires_at = EXCLUDED.access_token_expires_at, "
                "token_type = EXCLUDED.token_type, scope = EXCLUDED.scope",
                (
                    str(ctx.org_id), str(connector_id), ct, nonce, key_id,
                    bundle.refresh_token, bundle.expires_at, bundle.token_type, bundle.scope,
                ),
            )
            await conn.execute(
                "UPDATE connectors SET status = 'connected', updated_at = now() WHERE id = %s",
                (str(connector_id),),
            )

    async def create_oauth_connection(
        self,
        ctx: RequestContext,
        *,
        kind: str,
        name: str,
        config: dict[str, Any],
        bundle: "TokenBundle",
    ) -> UUID:
        """Create an account-scoped connector from an OAuth token bundle.

        Distinguishes OAuth-created personal connections from legacy org-scoped
        connectors by stamping ``account_id`` (the human who authorized).
        """
        await ctx.authorizer.require(ctx.principal, Permissions.CONNECTOR_MANAGE)
        build_connector(kind, config)  # validate kind early
        account_id = ctx.principal.account_id
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO connectors (org_id, kind, name, config, created_by, account_id) "
                "VALUES (%s,%s,%s,%s::jsonb,%s,%s) RETURNING id",
                (
                    str(ctx.org_id), kind, name, json.dumps(config),
                    str(ctx.principal.id),
                    str(account_id) if account_id else None,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        connector_id: UUID = row[0]
        await self.store_token_bundle(ctx, connector_id, bundle)
        await self.audit.record(
            agent=ctx.principal.attribution, action="connector.oauth_connect", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="connector",
            target_id=str(connector_id), request_id=ctx.request_id,
            after={"kind": kind, "name": name, "account_id": str(account_id) if account_id else None},
        )
        return connector_id

    async def list_connectors(self, ctx: RequestContext) -> list[dict[str, Any]]:
        # Discovery for MCP ``integration_list`` / ``integration_search`` — agents
        # have memory:read, not connector:manage. No secrets are returned.
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_READ)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT id, kind, name, status, created_at, account_id FROM connectors ORDER BY created_at"
            )
            rows = await cur.fetchall()
        return [
            {"id": str(r[0]), "kind": r[1], "name": r[2], "status": r[3],
             "created_at": r[4].isoformat() if r[4] else None,
             "account_id": str(r[5]) if r[5] else None}
            for r in rows
        ]

    async def get_connector(self, ctx: RequestContext, connector_id: UUID) -> dict[str, Any] | None:
        """Return one connector row (kind, name, status, config, account_id) or None."""
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT id, kind, name, status, config, account_id FROM connectors WHERE id = %s",
                (str(connector_id),),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]), "kind": row[1], "name": row[2], "status": row[3],
            "config": row[4] or {}, "account_id": str(row[5]) if row[5] else None,
        }

    async def get_token_bundle(self, ctx: RequestContext, connector_id: UUID) -> TokenBundle | None:
        """Decrypt and return the stored token bundle for a connector."""
        row = await self._raw_token(ctx, connector_id)
        if row is None:
            return None
        try:
            return self.vault.decrypt_bundle(row[0], row[1])
        except Exception:  # noqa: BLE001 - legacy single-token rows fall back
            return TokenBundle(access_token=self.vault.decrypt(row[0], row[1]))

    async def _raw_token(self, ctx: RequestContext, connector_id: UUID) -> tuple[Any, Any] | None:
        """Return the raw (ciphertext, nonce) row for a connector token."""
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT ciphertext, nonce FROM connector_tokens WHERE connector_id = %s",
                (str(connector_id),),
            )
            return await cur.fetchone()

    def _client_creds(self, kind: str) -> tuple[str, str]:
        """Return (client_id, client_secret) for ``kind`` from settings."""
        if self.settings is None:
            raise RuntimeError("connector service has no settings; cannot refresh OAuth tokens")
        if kind == "gmail":
            return self.settings.gmail_client_id or "", self.settings.gmail_client_secret or ""
        if kind == "slack":
            return self.settings.slack_client_id or "", self.settings.slack_client_secret or ""
        raise ValueError(f"no OAuth client creds for kind {kind!r}")

    async def refresh_if_needed(self, ctx: RequestContext, connector_id: UUID) -> TokenBundle | None:
        """Refresh the access token if expired; re-store the new bundle.

        Returns the current (possibly refreshed) bundle, or None if the
        connector has no stored token. Raises if the refresh fails.
        """
        conn = await self.get_connector(ctx, connector_id)
        if conn is None:
            return None
        kind = conn["kind"]
        if kind not in ("gmail", "slack"):
            # Non-OAuth connectors have nothing to refresh.
            return await self.get_token_bundle(ctx, connector_id)
        bundle = await self.get_token_bundle(ctx, connector_id)
        if bundle is None or not bundle.refresh_token:
            return bundle
        if not bundle.is_expired():
            return bundle
        client_id, client_secret = self._client_creds(kind)
        new_bundle = await oauth_mod.refresh_access_token(
            kind, refresh_token=bundle.refresh_token,
            client_id=client_id, client_secret=client_secret,
        )
        # Refresh is infrastructure for an already-authorized read/send path;
        # do not require connector:manage (agents only have memory:*).
        await self._persist_token_bundle(ctx, connector_id, new_bundle)
        log.info("oauth_token_refreshed", connector_id=str(connector_id), kind=kind)
        return new_bundle

    async def search(
        self, ctx: RequestContext, connector_id: UUID, *, query: str, max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Live search the connected source (not memory recall). Returns raw hits."""
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_READ)
        conn = await self.get_connector(ctx, connector_id)
        if conn is None:
            raise ValueError("connector not found")
        bundle = await self.refresh_if_needed(ctx, connector_id)
        if bundle is None:
            raise ValueError("connector has no stored token")
        adapter = build_connector(conn["kind"], conn["config"])
        if conn["kind"] == "gmail":
            return await adapter.list_messages(bundle.access_token, query, max_results=max_results)
        if conn["kind"] == "slack":
            # Slack has no free-text search over history; we list recent channel
            # messages and filter client-side for v1.
            channel = conn["config"].get("channel", "")
            result = await adapter.fetch(bundle.access_token, None)
            ql = query.lower()
            return [
                {"id": d.external_id, "text": d.content, "channel": channel}
                for d in result.documents
                if ql in d.content.lower()
            ][:max_results]
        raise ValueError(f"search not supported for kind {conn['kind']!r}")

    async def send(
        self,
        ctx: RequestContext,
        connector_id: UUID,
        *,
        kind: str | None = None,
        to: str | None = None,
        subject: str | None = None,
        body: str,
        channel: str | None = None,
        thread_id: str | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Send an email (gmail) or post a Slack message. Audited + episodic event."""
        # Outgoing actions are agent-usable (MCP ``integration_send``); keep
        # connect/disconnect/sync on connector:manage.
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_CREATE)
        conn = await self.get_connector(ctx, connector_id)
        if conn is None:
            raise ValueError("connector not found")
        ckind = conn["kind"]
        bundle = await self.refresh_if_needed(ctx, connector_id)
        if bundle is None:
            raise ValueError("connector has no stored token")
        adapter = build_connector(ckind, conn["config"])
        if ckind == "gmail":
            if not to:
                raise ValueError("gmail send requires 'to'")
            result = await adapter.send(
                bundle.access_token, to=to, subject=subject or "(no subject)",
                body=body, thread_id=thread_id,
            )
        elif ckind == "slack":
            target_channel = channel or conn["config"].get("channel")
            if not target_channel:
                raise ValueError("slack send requires 'channel'")
            result = await adapter.post_message(
                bundle.access_token, target_channel, body, thread_ts=thread_ts,
            )
        else:
            raise ValueError(f"send not supported for kind {ckind!r}")

        # Audit + episodic timeline event for the outgoing action.
        summary = self._outgoing_summary(ckind, to=to, subject=subject, channel=channel, body=body)
        await self.audit.record(
            agent=ctx.principal.attribution, action="connector.send", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="connector",
            target_id=str(connector_id), request_id=ctx.request_id, after={"kind": ckind, "summary": summary},
        )
        pipeline = self.ingestion_factory()
        await pipeline.ingest(
            ctx, summary, kind="event", scope="org", visibility="shared",
            subject=conn.get("name") or ckind,
            source="agent",
            source_ref={"connector_id": str(connector_id), "kind": ckind, "outgoing": True},
            tags=["integration", ckind, "outgoing"],
        )
        return {"sent": True, "kind": ckind, "result": result}

    @staticmethod
    def _outgoing_summary(
        kind: str, *, to: str | None, subject: str | None, channel: str | None, body: str
    ) -> str:
        preview = body if len(body) <= 200 else body[:200] + "…"
        if kind == "gmail":
            return f"Sent email to {to or '?'} — subject: {subject or '(no subject)'} — {preview}"
        if kind == "slack":
            return f"Posted in #{channel or '?'} — {preview}"
        return f"Sent via {kind}: {preview}"

    async def delete(self, ctx: RequestContext, connector_id: UUID) -> bool:
        await ctx.authorizer.require(ctx.principal, Permissions.CONNECTOR_MANAGE)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute("DELETE FROM connectors WHERE id = %s", (str(connector_id),))
            ok = cur.rowcount > 0
        await self.audit.record(
            agent=ctx.principal.attribution, action="connector.delete", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="connector",
            target_id=str(connector_id), request_id=ctx.request_id,
        )
        return ok

    async def sync(
        self, ctx: RequestContext, connector_id: UUID, *, connector: Connector | None = None
    ) -> SyncReport:
        """Fetch one page from the source and import it through ingestion."""
        await ctx.authorizer.require(ctx.principal, Permissions.CONNECTOR_MANAGE)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT kind, config FROM connectors WHERE id = %s", (str(connector_id),)
            )
            crow = await cur.fetchone()
            if crow is None:
                raise ValueError("connector not found")
            kind, config = crow[0], crow[1] or {}
            cur = await conn.execute(
                "SELECT cursor FROM connector_sync_state WHERE connector_id = %s",
                (str(connector_id),),
            )
            srow = await cur.fetchone()
            cursor = srow[0] if srow else None

        # OAuth connectors (gmail/slack) refresh their access token lazily;
        # legacy connectors keep the single-token decrypt path.
        if kind in ("gmail", "slack"):
            bundle = await self.refresh_if_needed(ctx, connector_id)
            token = bundle.access_token if bundle else ""
        else:
            trow = await self._raw_token(ctx, connector_id)
            token = self.vault.decrypt(trow[0], trow[1]) if trow else ""
        adapter = connector or build_connector(kind, config)
        result = await adapter.fetch(token, cursor)

        pipeline = self.ingestion_factory()
        imported = 0
        for doc in result.documents:
            await self._persist_source_doc(ctx, connector_id, doc)
            if doc.deleted:
                continue
            visibility = "shared" if doc.acl.get("public") else "private"
            res = await pipeline.ingest(
                ctx, doc.content,
                kind="note",
                scope=adapter.default_scope(),  # type: ignore[arg-type]
                visibility=visibility,  # type: ignore[arg-type]
                subject=doc.title,
                source="connector",
                source_ref={"connector_id": str(connector_id), "external_id": doc.external_id,
                            "uri": doc.uri, "acl": doc.acl},
            )
            if res.status != "duplicate":
                imported += 1

        async with self.db.org(ctx.org_id) as conn:
            await conn.execute(
                "INSERT INTO connector_sync_state (org_id, connector_id, cursor, last_synced_at, status) "
                "VALUES (%s,%s,%s,now(),'idle') "
                "ON CONFLICT (connector_id) DO UPDATE SET cursor = EXCLUDED.cursor, "
                "last_synced_at = now(), status = 'idle', error = NULL",
                (str(ctx.org_id), str(connector_id), result.next_cursor),
            )
        await self.audit.record(
            agent=ctx.principal.attribution, action="connector.sync", org_id=ctx.org_id,
            actor_type=ctx.principal.type, actor_id=ctx.principal.id, resource_type="connector",
            target_id=str(connector_id), request_id=ctx.request_id,
            after={"fetched": len(result.documents), "imported": imported},
        )
        return SyncReport(
            connector_id=connector_id, fetched=len(result.documents),
            imported=imported, next_cursor=result.next_cursor,
        )

    async def _persist_source_doc(
        self, ctx: RequestContext, connector_id: UUID, doc: Any
    ) -> None:
        async with self.db.org(ctx.org_id) as conn:
            await conn.execute(
                "INSERT INTO source_documents (org_id, connector_id, external_id, uri, acl, deleted_at) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s) "
                "ON CONFLICT (org_id, connector_id, external_id) DO UPDATE SET "
                "uri = EXCLUDED.uri, acl = EXCLUDED.acl, fetched_at = now(), "
                "deleted_at = EXCLUDED.deleted_at",
                (
                    str(ctx.org_id), str(connector_id), doc.external_id, doc.uri,
                    json.dumps(doc.acl), datetime.now(UTC) if doc.deleted else None,
                ),
            )
