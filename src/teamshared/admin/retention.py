"""Retention-policy enforcement for durable memory items."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb


async def enforce_retention(
    db: TenantDb,
    org_id: UUID,
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Apply every org policy, soft-deleting each matched item at most once."""
    async with db.org(org_id) as conn:
        cur = await conn.execute(
            "SELECT id, name, max_age_days, max_items, kinds "
            "FROM retention_policies ORDER BY created_at"
        )
        policies = await cur.fetchall()
        results: list[dict[str, Any]] = []
        total = 0
        for policy_id, name, max_age_days, max_items, raw_kinds in policies:
            kinds = list(raw_kinds or [])
            kind_clause = " AND kind = ANY(%s)" if kinds else ""
            params: list[Any] = []
            candidate_queries: list[str] = []

            if max_age_days is not None:
                age_params: list[Any] = [int(max_age_days)]
                if kinds:
                    age_params.append(kinds)
                params.extend(age_params)
                candidate_queries.append(
                    "SELECT id FROM memory_items "
                    "WHERE status = 'active' "
                    "AND created_at < now() - make_interval(days => %s)"
                    f"{kind_clause}"
                )

            if max_items is not None:
                item_params: list[Any] = []
                if kinds:
                    item_params.append(kinds)
                item_params.append(int(max_items))
                params.extend(item_params)
                candidate_queries.append(
                    "SELECT id FROM ("
                    "  SELECT id, row_number() OVER (ORDER BY created_at DESC, id DESC) AS rn "
                    "  FROM memory_items WHERE status = 'active'"
                    f"{kind_clause}"
                    ") ranked WHERE rn > %s"
                )

            if not candidate_queries:
                results.append(
                    {
                        "policy_id": str(policy_id),
                        "name": name,
                        "matched": 0,
                    }
                )
                continue

            union_sql = " UNION ".join(candidate_queries)
            if dry_run:
                cur = await conn.execute(
                    f"WITH candidates AS ({union_sql}) SELECT count(*) FROM candidates",
                    tuple(params),
                )
                row = await cur.fetchone()
                matched = int(row[0] or 0) if row else 0
            else:
                cur = await conn.execute(
                    f"""
                    WITH candidates AS ({union_sql})
                    UPDATE memory_items AS mi
                    SET status = 'soft_deleted', deleted_at = now(), updated_at = now()
                    FROM candidates
                    WHERE mi.id = candidates.id AND mi.status = 'active'
                    """,
                    tuple(params),
                )
                matched = cur.rowcount

            total += matched
            results.append(
                {
                    "policy_id": str(policy_id),
                    "name": name,
                    "matched": matched,
                }
            )
    return {
        "org_id": str(org_id),
        "dry_run": dry_run,
        "soft_deleted": 0 if dry_run else total,
        "would_soft_delete": total if dry_run else 0,
        "policies": results,
    }
