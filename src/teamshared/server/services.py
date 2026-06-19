"""Builds and holds the production (multi-tenant) service objects.

Kept separate from the legacy :class:`ServerState` so the new RLS/RBAC stack
can be wired into the HTTP app (under ``/v1``) without disturbing the existing
MCP tool surface during the migration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from teamshared.admin.service import AdminService
from teamshared.agents.runs import AgentRunStore
from teamshared.agents.service import AgentRunService
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
from teamshared.memory.hnsw_cache import HnswCache
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.skills import OrgSkillStore
from teamshared.memory.projects import ProjectStore
from teamshared.memory.retrieval import SecureRetrieval
from teamshared.memory.service import MemoryService
from teamshared.memory.strategic import OrgStrategicStore
from teamshared.memory.vectorstore import VectorStore
from teamshared.memory.wiki import WikiStore
from teamshared.memory.work import WorkStore
from teamshared.memory.working import WorkingMemory
from teamshared.queue.streams import StreamQueue
from teamshared.tenancy.context import TenantDb
from teamshared.tenancy.repository import TenancyRepository
from teamshared.workflow.orchestrator import WorkflowOrchestrator
from teamshared.workflow.runs import WorkflowRunStore

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
    agent_runs: AgentRunStore
    workflow_runs: WorkflowRunStore
    projects: ProjectStore
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
    graph: Any = None  # GraphStore | PostgresGraphStore | None — set at app startup

    def authorizer(self) -> Authorizer:
        """Fresh authorizer per request (its permission cache is request-scoped)."""
        return Authorizer(self.tenant_db)

    def retrieval(self) -> SecureRetrieval:
        return SecureRetrieval(self.vector_store, self.audit, self.strategic, self.work)

    def ingestion(self) -> IngestionPipeline:
        return IngestionPipeline(
            self.vector_store,
            self.approvals,
            self.audit,
            self.procedural,
            self.skills,
            self.strategic,
            self.work,
            graph=self.graph,
            autolink_enabled=self.settings.autolink_enabled,
        )

    def agent_run_service(self) -> AgentRunService:
        """Lifecycle facade for agent runs (enqueue needs a live Redis client)."""
        return AgentRunService(
            self.agent_runs, self.work, StreamQueue(self.working.client)
        )

    def workflow_orchestrator(self) -> WorkflowOrchestrator:
        """Procedural-loop engine; agent stages enqueue via the run service."""
        return WorkflowOrchestrator(
            runs=self.workflow_runs,
            work=self.work,
            procedural=self.procedural,
            agent_runs=self.agent_run_service(),
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
    approvals = ApprovalQueue(tenant_db)
    roles = RoleStore(tenant_db)
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
        agent_runs=AgentRunStore(tenant_db),
        workflow_runs=WorkflowRunStore(tenant_db),
        projects=ProjectStore(tenant_db),
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
                vector_store,
                approvals,
                audit,
                OrgProceduralStore(tenant_db),
                OrgSkillStore(tenant_db),
                OrgStrategicStore(tenant_db),
                WorkStore(tenant_db),
            ),
            audit=audit,
        ),
        admin=AdminService(
            tenant_db, roles, audit, export_max_items=settings.export_max_items
        ),
        consent=ConsentStore(tenant_db),
    )
    return services


async def build_services(settings: Settings) -> ProductionServices:
    services = make_services(settings)
    await services.tenant_db.connect()
    log.info("production_services_built", dsn=settings.pg_app_dsn.split("@")[-1])
    return services
