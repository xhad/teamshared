"""Private per-person soul profiles (org + account scoped).

A soul is a tiny compressed identity block for one human in one org — name,
role, style, likes/dislikes, choice patterns, dos/don'ts. Raw preferences may
accumulate elsewhere; this store holds only the curated, always-on digest
returned at session start. Callers must pass the subject's ``account_id`` —
rows are never listed org-wide for agents.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb

_FIELDS = ("org_id", "account_id", "body_md", "version", "token_est", "updated_by", "updated_at")
_SELECT = "org_id, account_id, body_md, version, token_est, updated_by, updated_at"

# Default char budget ≈ 600 tokens at chars/4 — keep session-start light.
DEFAULT_SOUL_MAX_CHARS = 2400


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars / 4) for soul metering."""
    return max(0, (len(text) + 3) // 4)


def compress_soul(body: str, max_chars: int = DEFAULT_SOUL_MAX_CHARS) -> str:
    """Hard-cap a soul body, keeping the leading identity section."""
    text = (body or "").strip()
    if not text:
        return ""
    if max_chars < 40:
        max_chars = 40
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "\n…(trimmed)\n"


def absorb_observation(
    existing: str | None,
    observation: str,
    *,
    max_chars: int = DEFAULT_SOUL_MAX_CHARS,
) -> str:
    """Append a preference/observation under ``## Notes`` and re-compress."""
    obs = (observation or "").strip()
    if not obs:
        return compress_soul(existing or "", max_chars)
    base = (existing or "").strip() or "# Soul"
    bullet = f"- {obs}"
    if bullet in base:
        return compress_soul(base, max_chars)
    if "## Notes" not in base:
        base = base.rstrip() + "\n\n## Notes\n"
    elif not base.endswith("\n"):
        base += "\n"
    return compress_soul(base + bullet + "\n", max_chars)


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    d = dict(zip(_FIELDS, row, strict=False))
    d["org_id"] = str(d["org_id"])
    d["account_id"] = str(d["account_id"])
    return d


class SoulStore:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def get(self, org_id: UUID, account_id: UUID) -> dict[str, Any] | None:
        """Return this person's private soul in ``org_id``, or ``None``."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_SELECT} FROM soul_profiles "
                "WHERE account_id = %s",
                (str(account_id),),
            )
            row = await cur.fetchone()
        return _row(row) if row else None

    async def upsert(
        self,
        org_id: UUID,
        account_id: UUID,
        *,
        body_md: str,
        updated_by: str = "system",
        max_chars: int = DEFAULT_SOUL_MAX_CHARS,
    ) -> dict[str, Any]:
        """Replace the soul body (always compressed to ``max_chars``)."""
        body = compress_soul(body_md, max_chars)
        tokens = estimate_tokens(body)
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"""
                INSERT INTO soul_profiles
                    (org_id, account_id, body_md, version, token_est, updated_by, updated_at)
                VALUES (%s, %s, %s, 1, %s, %s, now())
                ON CONFLICT (org_id, account_id) DO UPDATE SET
                    body_md = EXCLUDED.body_md,
                    version = soul_profiles.version + 1,
                    token_est = EXCLUDED.token_est,
                    updated_by = EXCLUDED.updated_by,
                    updated_at = now()
                RETURNING {_SELECT}
                """,
                (str(org_id), str(account_id), body, tokens, updated_by),
            )
            row = await cur.fetchone()
        if row is None:
            raise RuntimeError("soul upsert returned no row")
        return _row(row)

    async def absorb(
        self,
        org_id: UUID,
        account_id: UUID,
        observation: str,
        *,
        updated_by: str = "system",
        max_chars: int = DEFAULT_SOUL_MAX_CHARS,
    ) -> dict[str, Any]:
        """Fold one observation into the soul and rewrite the compressed body."""
        current = await self.get(org_id, account_id)
        existing = (current or {}).get("body_md") if current else None
        merged = absorb_observation(existing, observation, max_chars=max_chars)
        return await self.upsert(
            org_id,
            account_id,
            body_md=merged,
            updated_by=updated_by,
            max_chars=max_chars,
        )
