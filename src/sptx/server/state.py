"""Server-wide singleton holder.

FastMCP tool functions need access to the connected memory pillars. Rather
than threading them through every signature, we stash them on a single
:class:`ServerState` instance that the lifespan manager populates at startup
and tears down at shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass

from sptx.auth import TokenStore
from sptx.config import Settings
from sptx.memory.graph import GraphStore
from sptx.memory.procedural import ProceduralStore
from sptx.memory.recall import Recall
from sptx.memory.semantic import SemanticEpisodicStore
from sptx.memory.working import WorkingMemory


@dataclass
class ServerState:
    """All long-lived resources the server needs at request time."""

    settings: Settings
    tokens: TokenStore
    working: WorkingMemory
    semantic_episodic: SemanticEpisodicStore
    procedural: ProceduralStore
    recall: Recall
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
