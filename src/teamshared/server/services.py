"""Builds and holds the production (multi-tenant) service objects.

Kept separate from the legacy :class:`ServerState` so the new RLS/RBAC stack
can be wired into the HTTP app (under ``/v1``) without disturbing the existing
MCP tool surface during the migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from teamshared.admin.service import AdminService
from teamshared.config import Settings
from teamshared.connectors.service import ConnectorService
from teamshared.connectors.vault import TokenVault
from teamshared.identity.accounts import AccountStore
from teamshared.identity.api_keys import ApiKeyStore
from teamshared.identity.rbac import Authorizer
from teamshared.identity.roles import RoleStore
from teamshared.ingestion.pipeline import IngestionPipeline
from teamshared.logging import get_logger
from teamshared.memory.audit import AuditLog
from teamshared.memory.embeddings import Embedder, build_embedder
from teamshared.memory.hnsw_cache import HnswCache
from teamshared.memory.ontology import OntologyStore
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.projects import ProjectStore
from teamshared.memory.retrieval import SecureRetrieval
from teamshared.memory.service import MemoryService
from teamshared.memory.skills import OrgSkillStore
from teamshared.memory.soul import SoulStore
from teamshared.memory.strategic import OrgStrategicStore
from teamshared.memory.vectorstore import VectorStore
from teamshared.memory.wiki import WikiStore
from teamshared.memory.work import WorkStore
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
    skills: OrgSkillStore
    strategic: OrgStrategicStore
    work: WorkStore
    projects: ProjectStore
    wiki: WikiStore
    soul: SoulStore
    ontology: OntologyStore
    audit: AuditLog
    memory_service: MemoryService
    api_keys: ApiKeyStore
    roles: RoleStore
    accounts: AccountStore
    tenancy: TenancyRepository
    connectors: ConnectorService
    admin: AdminService
    graph: Any = None  # GraphStore | PostgresGraphStore | None — set at app startup

    def authorizer(self) -> Authorizer:
        """Fresh authorizer per request (its permission cache is request-scoped)."""
        return Authorizer(self.tenant_db)

    def retrieval(self) -> SecureRetrieval:
        return SecureRetrieval(self.vector_store, self.audit, self.strategic, self.work)

    def ingestion(self) -> IngestionPipeline:
        return IngestionPipeline(
            self.vector_store,
            self.audit,
            self.procedural,
            self.skills,
            self.strategic,
            self.work,
            graph=self.graph,
            autolink_enabled=self.settings.autolink_enabled,
            ontology=self.ontology,
        )


def make_services(settings: Settings) -> ProductionServices:
    """Assemble services without doing I/O.

    The ``TenantDb`` pool is created but not opened; the caller opens it (in the
    HTTP lifespan) before serving. This lets the app mount ``/v1`` at
    construction time while deferring the connection.
    """
    tenant_db = TenantDb(settings.pg_app_dsn)
    embedder = build_embedder(settings)
    hnsw_cache = HnswCache(settings.embed_dims, enabled=settings.hnsw_cache_enabled)
    vector_store = VectorStore(tenant_db, embedder, cache=hnsw_cache)
    audit = AuditLog(tenant_db)
    memory_service = MemoryService(vector_store, audit)
    roles = RoleStore(tenant_db)
    ontology = OntologyStore(tenant_db)
    services = ProductionServices(
        settings=settings,
        tenant_db=tenant_db,
        working=WorkingMemory(
            settings.redis_url,
            default_ttl=settings.session_ttl,
            job_signing_secret=settings.job_signing_secret,
        ),
        embedder=embedder,
        vector_store=vector_store,
        procedural=OrgProceduralStore(tenant_db),
        skills=OrgSkillStore(tenant_db),
        strategic=OrgStrategicStore(tenant_db),
        work=WorkStore(tenant_db),
        projects=ProjectStore(tenant_db),
        wiki=WikiStore(tenant_db),
        soul=SoulStore(tenant_db),
        ontology=ontology,
        audit=audit,
        memory_service=memory_service,
        api_keys=ApiKeyStore(tenant_db),
        roles=roles,
        accounts=AccountStore(tenant_db),
        tenancy=TenancyRepository(tenant_db),
        connectors=ConnectorService(
            tenant_db,
            TokenVault(settings.connector_encryption_key),
            ingestion_factory=lambda: IngestionPipeline(
                vector_store,
                audit,
                OrgProceduralStore(tenant_db),
                OrgSkillStore(tenant_db),
                OrgStrategicStore(tenant_db),
                WorkStore(tenant_db),
                ontology=ontology,
            ),
            audit=audit,
        ),
        admin=AdminService(
            tenant_db, roles, audit, export_max_items=settings.export_max_items
        ),
    )
    return services


async def build_services(settings: Settings) -> ProductionServices:
    services = make_services(settings)
    await services.tenant_db.connect()
    log.info("production_services_built", dsn=settings.pg_app_dsn.split("@")[-1])
    return services
