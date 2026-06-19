"""Server-wide singleton holder.

FastMCP tool functions need access to the connected memory pillars. Rather
than threading them through every signature, we stash them on a single
:class:`ServerState` instance that the lifespan manager populates at startup
and tears down at shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass

from teamshared.config import Settings
from teamshared.invite import InviteStore
from teamshared.memory.agent_state import AgentStateStore
from teamshared.memory.audit import AuditLog
from teamshared.memory.facade import MemoryFacade
from teamshared.memory.graph import GraphStore
from teamshared.memory.graph_pg import PostgresGraphStore
from teamshared.memory.procedural import OrgProceduralStore
from teamshared.memory.working import WorkingMemory
from teamshared.server.services import ProductionServices
from teamshared.tenancy.context import TenantDb


@dataclass
class ServerState:
    """All long-lived resources the server needs at request time.

    Post-G2 the MCP tools call through :attr:`facade`, which routes durable
    pillars to :attr:`services` (pgvector RLS) and the volatile pillars to the
    org-scoped Redis/Neo4j stores.
    """

    settings: Settings
    invites: InviteStore
    working: WorkingMemory
    agent_state: AgentStateStore
    procedural: OrgProceduralStore
    services: ProductionServices
    facade: MemoryFacade
    audit: AuditLog
    graph: GraphStore | PostgresGraphStore | None = None
    audit_db: TenantDb | None = None


_state: ServerState | None = None


def set_state(state: ServerState) -> None:
    global _state
    _state = state


def get_state() -> ServerState:
    if _state is None:
        raise RuntimeError(
            "Server state not initialized. The server lifespan must call set_state()."
        )
    return _state


def clear_state() -> None:
    global _state
    _state = None
