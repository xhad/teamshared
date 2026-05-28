"""Server-wide singleton holder.

FastMCP tool functions need access to the connected memory pillars. Rather
than threading them through every signature, we stash them on a single
:class:`ServerState` instance that the lifespan manager populates at startup
and tears down at shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass

from teamshared.auth import TokenStore
from teamshared.config import Settings
from teamshared.invite import InviteStore
from teamshared.memory.agent_state import AgentStateStore
from teamshared.memory.audit import AuditLog
from teamshared.memory.graph import GraphStore
from teamshared.memory.procedural import ProceduralStore
from teamshared.memory.recall import Recall
from teamshared.memory.semantic import SemanticEpisodicStore
from teamshared.memory.working import WorkingMemory


@dataclass
class ServerState:
    """All long-lived resources the server needs at request time."""

    settings: Settings
    tokens: TokenStore
    invites: InviteStore
    working: WorkingMemory
    agent_state: AgentStateStore
    semantic_episodic: SemanticEpisodicStore
    procedural: ProceduralStore
    recall: Recall
    audit: AuditLog
    graph: GraphStore | None = None


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
