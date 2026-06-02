"""Builds and holds the production (multi-tenant) service objects.

Kept separate from the legacy :class:`ServerState` so the new RLS/RBAC stack
can be wired into the HTTP app (under ``/v1``) without disturbing the existing
MCP tool surface during the migration.
"""

from __future__ import annotations

from dataclasses import dataclass

from teamshared.admin.service import AdminService
from teamshared.config import Settings
from teamshared.connectors.service import ConnectorService
from teamshared.connectors.vault import TokenVault
from teamshared.identity.accounts import AccountStore
from teamshared.identity.api_keys import ApiKeyStore
from teamshared.identity.rbac import Authorizer
from teamshared.identity.roles import RoleStore
from teamshared.ingestion.approvals import ApprovalQueue
from teamshared.ingestion.consent import ConsentStore
from teamshared.ingestion.pipeline import IngestionPipeline
from teamshared.logging import get_logger
from teamshared.memory.audit import AuditLog
from teamshared.memory.embeddings import Embedder, build_embedder
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.retrieval import SecureRetrieval
from teamshared.memory.service import MemoryService
from teamshared.memory.vectorstore import VectorStore
from teamshared.memory.wiki import WikiStore
from teamshared.memory.working import WorkingMemory
from teamshared.tenancy.context import TenantDb
from teamshared.tenancy.repository import TenancyRepository

log = get_logger(__name__)


@dataclass
class ProductionServices:
    settings: Settings
    tenant_db: TenantDb
    working: WorkingMemory
    embedder: Embedder
    vector_store: VectorStore
    procedural: OrgProceduralStore
    wiki: WikiStore
    audit: AuditLog
    memory_service: MemoryService
    approvals: ApprovalQueue
    api_keys: ApiKeyStore
    roles: RoleStore
    accounts: AccountStore
    tenancy: TenancyRepository
    connectors: ConnectorService
    admin: AdminService
    consent: ConsentStore

    def authorizer(self) -> Authorizer:
        """Fresh authorizer per request (its permission cache is request-scoped)."""
        return Authorizer(self.tenant_db)

    def retrieval(self) -> SecureRetrieval:
        return SecureRetrieval(self.vector_store, self.audit)

    def ingestion(self) -> IngestionPipeline:
        return IngestionPipeline(
            self.vector_store, self.approvals, self.audit, self.authorizer()
        )


def make_services(settings: Settings) -> ProductionServices:
    """Assemble services without doing I/O.

    The ``TenantDb`` pool is created but not opened; the caller opens it (in the
    HTTP lifespan) before serving. This lets the app mount ``/v1`` at
    construction time while deferring the connection.
    """
    tenant_db = TenantDb(settings.pg_app_dsn)
    embedder = build_embedder(settings)
    vector_store = VectorStore(tenant_db, embedder)
    audit = AuditLog(tenant_db)
    authorizer = Authorizer(tenant_db)
    memory_service = MemoryService(vector_store, audit, authorizer)
    approvals = ApprovalQueue(tenant_db)
    roles = RoleStore(tenant_db)
    services = ProductionServices(
        settings=settings,
        tenant_db=tenant_db,
        working=WorkingMemory(settings.redis_url, default_ttl=settings.session_ttl),
        embedder=embedder,
        vector_store=vector_store,
        procedural=OrgProceduralStore(tenant_db),
        wiki=WikiStore(tenant_db),
        audit=audit,
        memory_service=memory_service,
        approvals=approvals,
        api_keys=ApiKeyStore(tenant_db),
        roles=roles,
        accounts=AccountStore(tenant_db),
        tenancy=TenancyRepository(tenant_db),
        connectors=ConnectorService(
            tenant_db,
            TokenVault(settings.connector_encryption_key),
            ingestion_factory=lambda: IngestionPipeline(
                vector_store, approvals, audit, Authorizer(tenant_db)
            ),
            audit=audit,
        ),
        admin=AdminService(tenant_db, roles, audit),
        consent=ConsentStore(tenant_db),
    )
    return services


async def build_services(settings: Settings) -> ProductionServices:
    services = make_services(settings)
    await services.tenant_db.connect()
    log.info("production_services_built", dsn=settings.pg_app_dsn.split("@")[-1])
    return services
