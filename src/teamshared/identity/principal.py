"""The resolved identity for an authenticated request."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

PrincipalType = Literal["user", "agent", "api_key", "service"]


@dataclass(frozen=True)
class Principal:
    """Who is making the request, within which org, with what scopes.

    ``type``/``id`` identify the underlying actor (the user or agent the key
    acts for). ``scopes`` are the permission codes the presenting API key is
    allowed to use; an empty tuple means "inherit the actor's role permissions
    without an extra cap". ``api_key_id`` is set when auth came from a key.
    """

    org_id: UUID
    type: PrincipalType
    id: UUID
    scopes: tuple[str, ...] = ()
    api_key_id: UUID | None = None
    display: str | None = None
    roles: tuple[str, ...] = field(default=())

    @property
    def attribution(self) -> str:
        """Stable string used for memory authorship/audit ``agent`` columns."""
        return self.display or f"{self.type}:{self.id}"
