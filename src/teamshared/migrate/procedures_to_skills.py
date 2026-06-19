"""Copy atomic procedures (misclassified skills) into the skills pillar."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb

_MIGRATION_TAG = "migrated-from-procedure"


@dataclass
class ProcedureRow:
    id: int
    org_id: UUID
    name: str
    version: int
    description: str | None
    steps_md: str
    tool_recipe: dict[str, Any] | None
    tags: list[str]
    created_by: str
    status: str


@dataclass
class MigrationPlan:
    migrate: list[ProcedureRow] = field(default_factory=list)
    skip_workflow: list[ProcedureRow] = field(default_factory=list)
    skip_composed: list[ProcedureRow] = field(default_factory=list)
    skip_exists: list[ProcedureRow] = field(default_factory=list)


@dataclass
class MigrationResult:
    migrated: int = 0
    retired: int = 0
    skipped: int = 0
    names: list[str] = field(default_factory=list)


def classify_procedure(tool_recipe: Any) -> str:
    """Return ``atomic``, ``workflow``, or ``composed`` for a procedure row."""
    if not isinstance(tool_recipe, dict) or not tool_recipe:
        return "atomic"
    if tool_recipe.get("stages") is not None:
        return "workflow"
    if tool_recipe.get("skills"):
        return "composed"
    return "atomic"


def tool_recipe_to_hints(tool_recipe: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map a procedure ``tool_recipe`` to skill ``tool_hints`` when safe."""
    if not tool_recipe:
        return None
    if classify_procedure(tool_recipe) != "atomic":
        return None
    return dict(tool_recipe)


async def list_active_procedures(db: TenantDb, org_id: UUID) -> list[ProcedureRow]:
    async with db.org(org_id) as conn:
        cur = await conn.execute(
            """
            SELECT id, org_id, name, version, description, steps_md, tool_recipe,
                   tags, created_by, status
            FROM procedures
            WHERE status = 'active'
            ORDER BY name, version
            """,
        )
        rows = await cur.fetchall()
    out: list[ProcedureRow] = []
    for row in rows:
        recipe = row[6]
        if isinstance(recipe, str):
            recipe = json.loads(recipe)
        out.append(
            ProcedureRow(
                id=int(row[0]),
                org_id=UUID(str(row[1])),
                name=str(row[2]),
                version=int(row[3]),
                description=row[4],
                steps_md=str(row[5]),
                tool_recipe=recipe if isinstance(recipe, dict) else None,
                tags=list(row[7] or []),
                created_by=str(row[8]),
                status=str(row[9]),
            )
        )
    return out


async def skill_version_exists(
    db: TenantDb, org_id: UUID, name: str, version: int
) -> bool:
    async with db.org(org_id) as conn:
        cur = await conn.execute(
            "SELECT 1 FROM skills WHERE name = %s AND version = %s LIMIT 1",
            (name, version),
        )
        return (await cur.fetchone()) is not None


async def plan_migration(
    db: TenantDb,
    org_id: UUID,
    *,
    include_composed: bool = False,
) -> MigrationPlan:
    plan = MigrationPlan()
    for proc in await list_active_procedures(db, org_id):
        kind = classify_procedure(proc.tool_recipe)
        if kind == "workflow":
            plan.skip_workflow.append(proc)
            continue
        if kind == "composed" and not include_composed:
            plan.skip_composed.append(proc)
            continue
        if await skill_version_exists(db, org_id, proc.name, proc.version):
            plan.skip_exists.append(proc)
            continue
        plan.migrate.append(proc)
    return plan


async def apply_migration(
    db: TenantDb,
    org_id: UUID,
    plan: MigrationPlan,
) -> MigrationResult:
    result = MigrationResult()
    if not plan.migrate:
        result.skipped = (
            len(plan.skip_workflow) + len(plan.skip_composed) + len(plan.skip_exists)
        )
        return result

    async with db.org(org_id) as conn:
        for proc in plan.migrate:
            tags = list(proc.tags)
            if _MIGRATION_TAG not in tags:
                tags.append(_MIGRATION_TAG)
            hints = tool_recipe_to_hints(proc.tool_recipe)
            hints_json = json.dumps(hints) if hints is not None else None
            await conn.execute(
                """
                INSERT INTO skills
                    (org_id, scope, name, version, description, body_md, tool_hints,
                     tags, created_by, created_at, status)
                VALUES (%s, 'org', %s, %s, %s, %s, %s::jsonb, %s, %s, now(), 'active')
                ON CONFLICT (org_id, name, version) DO NOTHING
                """,
                (
                    str(org_id),
                    proc.name,
                    proc.version,
                    proc.description,
                    proc.steps_md,
                    hints_json,
                    tags,
                    proc.created_by,
                ),
            )
            result.migrated += 1
            if proc.name not in result.names:
                result.names.append(proc.name)

        for name in result.names:
            cur = await conn.execute(
                """
                UPDATE procedures SET status = 'soft_deleted'
                WHERE name = %s AND status = 'active'
                """,
                (name,),
            )
            result.retired += cur.rowcount or 0

    result.skipped = len(plan.skip_workflow) + len(plan.skip_composed) + len(plan.skip_exists)
    return result


async def list_org_ids(dsn: str) -> list[UUID]:
    """Distinct org ids with active or historical procedures (admin DSN)."""
    pool = TenantDb(dsn)
    await pool.connect()
    try:
        async with pool.pool.connection() as conn:
            cur = await conn.execute(
                "SELECT DISTINCT org_id FROM procedures WHERE org_id IS NOT NULL ORDER BY 1"
            )
            rows = await cur.fetchall()
    finally:
        await pool.close()
    return [UUID(str(row[0])) for row in rows]
