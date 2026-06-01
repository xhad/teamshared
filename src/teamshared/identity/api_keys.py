"""Hashed, scoped API keys -- the production replacement for the JSON token file.

A key looks like ``tsk_<prefix>_<secret>``. Only the ``tsk_<prefix>`` segment
and a scrypt hash of the whole token are persisted; the raw secret is returned
once at mint time and is unrecoverable thereafter. Authentication resolves the
candidate row by globally-unique prefix through the ``auth_lookup_api_key``
SECURITY DEFINER function (so it works before any org context exists), then
verifies the hash in constant time.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from teamshared.identity.hashing import hash_secret, verify_secret
from teamshared.identity.principal import Principal, PrincipalType
from teamshared.logging import get_logger
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)

_KEY_PREFIX = "tsk"


@dataclass(frozen=True)
class MintedKey:
    id: UUID
    prefix: str
    token: str  # full secret, shown once


class ApiKeyStore:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def mint(
        self,
        *,
        org_id: UUID,
        principal_type: PrincipalType,
        principal_id: UUID,
        name: str,
        scopes: list[str] | None = None,
        created_by: UUID | None = None,
        expires_at: datetime | None = None,
    ) -> MintedKey:
        prefix = f"{_KEY_PREFIX}_{secrets.token_hex(4)}"
        secret = secrets.token_urlsafe(32)
        token = f"{prefix}_{secret}"
        key_hash = hash_secret(token)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "INSERT INTO api_keys "
                "(org_id, name, prefix, key_hash, principal_type, principal_id, scopes, "
                " created_by, expires_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    str(org_id), name, prefix, key_hash, principal_type, str(principal_id),
                    scopes or [], str(created_by) if created_by else None, expires_at,
                ),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("api_key insert returned no row")
        return MintedKey(id=row[0], prefix=prefix, token=token)

    async def authenticate(self, token: str) -> Principal | None:
        """Resolve a bearer token to a :class:`Principal`, or ``None`` if invalid."""
        if not token or not token.startswith(_KEY_PREFIX + "_"):
            return None
        # Prefix is the first two segments (``tsk_<hex>``). The url-safe secret
        # may itself contain ``_``, so split off only the leading two fields
        # rather than rpartition (which would fold secret bytes into the prefix).
        parts = token.split("_", 2)
        if len(parts) < 3:
            return None
        prefix = f"{parts[0]}_{parts[1]}"
        async with self.db.admin() as conn:
            cur = await conn.execute(
                "SELECT id, org_id, key_hash, principal_type, principal_id, scopes, "
                "expires_at, revoked_at FROM auth_lookup_api_key(%s)",
                (prefix,),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        key_id, org_id, key_hash, ptype, pid, scopes, expires_at, revoked_at = row
        if revoked_at is not None:
            return None
        if expires_at is not None and expires_at < datetime.now(UTC):
            return None
        if not verify_secret(token, key_hash):
            log.warning("api_key_hash_mismatch", prefix=prefix)
            return None
        async with self.db.admin() as conn:
            await conn.execute("SELECT auth_touch_api_key(%s)", (str(key_id),))
        return Principal(
            org_id=org_id,
            type=ptype,
            id=pid,
            scopes=tuple(scopes or ()),
            api_key_id=key_id,
        )

    async def revoke(self, org_id: UUID, key_id: UUID) -> bool:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "UPDATE api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
                (str(key_id),),
            )
            return cur.rowcount > 0

    async def list_keys(self, org_id: UUID) -> list[dict[str, object]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id, name, prefix, principal_type, principal_id, scopes, "
                "created_at, last_used_at, expires_at, revoked_at FROM api_keys "
                "ORDER BY created_at DESC"
            )
            rows = await cur.fetchall()
        return [
            {
                "id": str(r[0]), "name": r[1], "prefix": r[2], "principal_type": r[3],
                "principal_id": str(r[4]), "scopes": list(r[5] or []),
                "created_at": r[6].isoformat() if r[6] else None,
                "last_used_at": r[7].isoformat() if r[7] else None,
                "expires_at": r[8].isoformat() if r[8] else None,
                "revoked": r[9] is not None,
            }
            for r in rows
        ]
