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
from teamshared.connectors.registry import build_connector
from teamshared.connectors.vault import TokenVault
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
    ) -> None:
        self.db = db
        self.vault = vault
        self.ingestion_factory = ingestion_factory
        self.audit = audit

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

    async def list_connectors(self, ctx: RequestContext) -> list[dict[str, Any]]:
        await ctx.authorizer.require(ctx.principal, Permissions.CONNECTOR_MANAGE)
        async with self.db.org(ctx.org_id) as conn:
            cur = await conn.execute(
                "SELECT id, kind, name, status, created_at FROM connectors ORDER BY created_at"
            )
            rows = await cur.fetchall()
        return [
            {"id": str(r[0]), "kind": r[1], "name": r[2], "status": r[3],
             "created_at": r[4].isoformat() if r[4] else None}
            for r in rows
        ]

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
                "SELECT ciphertext, nonce FROM connector_tokens WHERE connector_id = %s",
                (str(connector_id),),
            )
            trow = await cur.fetchone()
            cur = await conn.execute(
                "SELECT cursor FROM connector_sync_state WHERE connector_id = %s",
                (str(connector_id),),
            )
            srow = await cur.fetchone()
            cursor = srow[0] if srow else None

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
