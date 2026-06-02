"""Consent grants: the human gate for what an agent may capture into memory.

Capture is OFF unless an active grant exists for the agent whose ``scope`` covers
the capability being captured. "Active" means not revoked, not expired, and
``mode != 'off'``. This enforces the consent-first principle: nothing is captured
or pulled without a human's explicit, recorded approval.

The store is tenant-scoped (RLS via :class:`TenantDb`), mirroring the other
governance store, :class:`teamshared.ingestion.approvals.ApprovalQueue`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb

# Capture capabilities a grant's ``scope`` may include.
CAP_TOOL_CALLS = "tool_calls"
CAP_DISTILLED = "distilled_facts_only"
CAP_RAW_TURNS = "raw_turns"
SCOPES: tuple[str, ...] = (CAP_TOOL_CALLS, CAP_DISTILLED, CAP_RAW_TURNS)

MODES: tuple[str, ...] = ("review", "policy", "off")

# Baseline sanitization the client must enforce before sending. Rules in
# ``LOCKED_RULES`` cannot be loosened by a per-grant override.
BASELINE_PROFILE: dict[str, bool] = {
    "redact_secrets": True,
    "redact_emails": True,
    "redact_file_paths": True,
    "redact_ip_addresses": True,
    "drop_high_entropy": True,
}
LOCKED_RULES: tuple[str, ...] = ("redact_secrets",)


def _merge_profile(override: dict[str, bool] | None) -> dict[str, bool]:
    profile = {**BASELINE_PROFILE, **(override or {})}
    for rule in LOCKED_RULES:
        profile[rule] = True
    return profile


def _status(mode: str, expires_at: datetime | None, revoked_at: datetime | None) -> str:
    if revoked_at is not None:
        return "revoked"
    if mode == "off":
        return "off"
    if expires_at is not None and expires_at <= datetime.now(UTC):
        return "expired"
    return "active"


class ConsentStore:
    """Read/write consent grants and answer capture-time allow checks."""

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def grant(
        self,
        org_id: UUID,
        *,
        agent: str,
        mode: str = "review",
        scope: list[str] | tuple[str, ...] = (),
        sanitization_profile: dict[str, bool] | None = None,
        granted_by: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> UUID:
        """Record a new consent grant; returns its id. The newest non-revoked,
        non-expired grant for an agent is the one capture consults."""
        clean_scope = [s for s in scope if s in SCOPES]
        profile = _merge_profile(sanitization_profile)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO consent_grants "
                "(org_id, agent, mode, scope, sanitization_profile, granted_by, expires_at) "
                "VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s) RETURNING id",
                (
                    str(org_id), agent, mode, clean_scope, json.dumps(profile),
                    str(granted_by) if granted_by else None, expires_at,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        grant_id: UUID = row[0]
        return grant_id

    async def revoke(self, org_id: UUID, grant_id: UUID | str) -> bool:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "UPDATE consent_grants SET revoked_at = now() "
                "WHERE id = %s AND revoked_at IS NULL",
                (str(grant_id),),
            )
            return cur.rowcount > 0

    async def active_grant(self, org_id: UUID, agent: str) -> dict[str, Any] | None:
        """The grant capture consults for ``agent``: newest active one, or None."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id, agent, mode, scope, sanitization_profile, granted_by, "
                "granted_at, expires_at FROM consent_grants "
                "WHERE agent = %s AND revoked_at IS NULL AND mode <> 'off' "
                "AND (expires_at IS NULL OR expires_at > now()) "
                "ORDER BY granted_at DESC LIMIT 1",
                (agent,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]), "agent": row[1], "mode": row[2],
            "scope": list(row[3] or []), "sanitization_profile": row[4],
            "granted_by": str(row[5]) if row[5] else None,
            "granted_at": row[6].isoformat() if row[6] else None,
            "expires_at": row[7].isoformat() if row[7] else None,
        }

    async def capture_allowed(self, org_id: UUID, agent: str, capability: str) -> bool:
        """True only when an active grant for ``agent`` covers ``capability``."""
        grant = await self.active_grant(org_id, agent)
        return bool(grant and capability in grant["scope"])

    async def list_grants(self, org_id: UUID) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id, agent, mode, scope, granted_by, granted_at, expires_at, revoked_at "
                "FROM consent_grants ORDER BY granted_at DESC"
            )
            rows = await cur.fetchall()
        return [
            {
                "id": str(r[0]), "agent": r[1], "mode": r[2],
                "scope": list(r[3] or []),
                "granted_by": str(r[4]) if r[4] else None,
                "granted_at": r[5].isoformat() if r[5] else None,
                "expires_at": r[6].isoformat() if r[6] else None,
                "revoked_at": r[7].isoformat() if r[7] else None,
                "status": _status(r[2], r[6], r[7]),
            }
            for r in rows
        ]
