"""Global email identity (accounts) -- the cross-org link for human sign-in.

A human is one ``accounts`` row (globally-unique, lowercased email) that can own
or belong to many orgs; each org keeps its own ``users`` row linked back via
``account_id``. Both operations here run *before/without* an org context and
across orgs, so they go through the SECURITY DEFINER functions added in
migration 013 (``provision_account`` / ``auth_account_orgs``) over an
RLS-less ``admin()`` connection. Never read ``accounts`` under ``db.org(...)`` --
it is locked (RLS + FORCE, no policy) and will return zero rows.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb


class AccountStore:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def upsert(self, email: str, display_name: str | None = None) -> UUID:
        """Create or refresh the global account for ``email``; return its id."""
        async with self.db.admin() as conn:
            cur = await conn.execute(
                "SELECT id FROM provision_account(%s, %s)",
                (email.strip().lower(), display_name),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("provision_account returned no row")
        account_id: UUID = row[0]
        return account_id

    async def list_orgs(self, email: str) -> list[dict[str, Any]]:
        """Every active org this email belongs to, with its per-org user id + role."""
        async with self.db.admin() as conn:
            cur = await conn.execute(
                "SELECT org_id, user_id, org_slug, org_name, role "
                "FROM auth_account_orgs(%s)",
                (email.strip().lower(),),
            )
            rows = await cur.fetchall()
        return [
            {
                "org_id": r[0], "user_id": r[1], "slug": r[2],
                "name": r[3], "role": r[4],
            }
            for r in rows
        ]
