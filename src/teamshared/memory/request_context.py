"""Per-request context: who is asking, in which tenant, with what reach.

Built once per inbound request from the authenticated :class:`Principal`. It
knows how to compute the principal's accessible scopes (org + own user/agent +
member teams + their projects) so retrieval can pre-filter in SQL.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from uuid import UUID

from teamshared.identity.principal import Principal
from teamshared.identity.rbac import Authorizer
from teamshared.memory.vectorstore import ScopeFilter
from teamshared.tenancy.context import TenantDb


@dataclass
class RequestContext:
    principal: Principal
    db: TenantDb
    authorizer: Authorizer
    request_id: str = field(default_factory=lambda: secrets.token_hex(8))

    @property
    def org_id(self) -> UUID:
        return self.principal.org_id

    async def _member_team_ids(self) -> list[UUID]:
        if self.principal.type != "user":
            return []
        async with self.db.org(self.org_id) as conn:
            cur = await conn.execute(
                "SELECT team_id FROM team_members WHERE user_id = %s",
                (str(self.principal.id),),
            )
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def _project_ids_for_teams(self, team_ids: list[UUID]) -> list[UUID]:
        if not team_ids:
            return []
        async with self.db.org(self.org_id) as conn:
            cur = await conn.execute(
                "SELECT id FROM projects WHERE team_id = ANY(%s)",
                ([str(t) for t in team_ids],),
            )
            rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def accessible_scope_filter(self, *, include_shared: bool = True) -> ScopeFilter:
        team_ids = await self._member_team_ids()
        project_ids = await self._project_ids_for_teams(team_ids)
        return ScopeFilter(
            user_id=self.principal.id if self.principal.type == "user" else None,
            agent_id=self.principal.id if self.principal.type == "agent" else None,
            team_ids=team_ids,
            project_ids=project_ids,
            include_org=True,
            include_shared=include_shared,
        )
