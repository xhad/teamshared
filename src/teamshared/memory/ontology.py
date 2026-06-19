"""Org ontology store: link types, object kinds, interfaces, governed actions, entity views."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from teamshared.logging import get_logger
from teamshared.memory.wiki import slugify
from teamshared.seed.ontology import (
    KIND_INTERFACE_MAP,
    STARTER_ACTION_TYPES,
    STARTER_INTERFACES,
    STARTER_LINK_TYPES,
    STARTER_OBJECT_KINDS,
)
from teamshared.tenancy.context import TenantDb

log = get_logger(__name__)


class OntologyError(Exception):
    """Raised when ontology validation fails."""


class OntologyStore:
    """Postgres-backed org ontology registry and action log."""

    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def seed_defaults(self, org_id: UUID) -> dict[str, int]:
        """Idempotently insert starter link types, kinds, interfaces, and actions."""
        counts = {"link_types": 0, "object_kinds": 0, "interfaces": 0, "action_types": 0}
        async with self.db.org(org_id) as conn:
            for name, desc, from_kinds, to_kinds, card in STARTER_LINK_TYPES:
                cur = await conn.execute(
                    """
                    INSERT INTO ontology_link_types
                        (org_id, name, description, from_kinds, to_kinds, cardinality)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (org_id, name) DO NOTHING
                    RETURNING id
                    """,
                    (str(org_id), name, desc, from_kinds, to_kinds, card),
                )
                if await cur.fetchone():
                    counts["link_types"] += 1

            kind_ids: dict[str, UUID] = {}
            for name, desc, schema in STARTER_OBJECT_KINDS:
                cur = await conn.execute(
                    """
                    INSERT INTO ontology_object_kinds
                        (org_id, name, description, properties_schema)
                    VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (org_id, name) DO NOTHING
                    RETURNING id
                    """,
                    (str(org_id), name, desc, _json(schema)),
                )
                row = await cur.fetchone()
                if row:
                    kind_ids[name] = row[0]
                    counts["object_kinds"] += 1

            cur = await conn.execute(
                "SELECT name, id FROM ontology_object_kinds WHERE org_id = %s",
                (str(org_id),),
            )
            for row in await cur.fetchall():
                kind_ids[row[0]] = row[1]

            iface_ids: dict[str, UUID] = {}
            for name, desc, traits in STARTER_INTERFACES:
                cur = await conn.execute(
                    """
                    INSERT INTO ontology_interfaces (org_id, name, description, traits)
                    VALUES (%s, %s, %s, %s::jsonb)
                    ON CONFLICT (org_id, name) DO NOTHING
                    RETURNING id
                    """,
                    (str(org_id), name, desc, _json(traits)),
                )
                row = await cur.fetchone()
                if row:
                    iface_ids[name] = row[0]
                    counts["interfaces"] += 1

            cur = await conn.execute(
                "SELECT name, id FROM ontology_interfaces WHERE org_id = %s",
                (str(org_id),),
            )
            for row in await cur.fetchall():
                iface_ids[row[0]] = row[1]

            for kind_name, iface_names in KIND_INTERFACE_MAP.items():
                kind_id = kind_ids.get(kind_name)
                if kind_id is None:
                    continue
                for iface_name in iface_names:
                    iface_id = iface_ids.get(iface_name)
                    if iface_id is None:
                        continue
                    await conn.execute(
                        """
                        INSERT INTO ontology_kind_interfaces (org_id, kind_id, interface_id)
                        VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (str(org_id), str(kind_id), str(iface_id)),
                    )

            for name, desc, tool, schema, approval in STARTER_ACTION_TYPES:
                cur = await conn.execute(
                    """
                    INSERT INTO ontology_action_types
                        (org_id, name, description, wrapper_tool, parameters_schema, requires_approval)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                    ON CONFLICT (org_id, name) DO NOTHING
                    RETURNING id
                    """,
                    (str(org_id), name, desc, tool, _json(schema), approval),
                )
                if await cur.fetchone():
                    counts["action_types"] += 1

        return counts

    async def list_link_types(self, org_id: UUID) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT name, description, from_kinds, to_kinds, cardinality
                FROM ontology_link_types
                WHERE org_id = %s
                ORDER BY name
                """,
                (str(org_id),),
            )
            rows = await cur.fetchall()
        return [
            {
                "name": r[0],
                "description": r[1],
                "from_kinds": list(r[2] or []),
                "to_kinds": list(r[3] or []),
                "cardinality": r[4],
            }
            for r in rows
        ]

    async def validate_predicate(self, org_id: UUID, predicate: str) -> None:
        """Reject unknown predicates when the org has a link-type registry."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT 1 FROM ontology_link_types WHERE org_id = %s LIMIT 1",
                (str(org_id),),
            )
            if await cur.fetchone() is None:
                return
            cur = await conn.execute(
                "SELECT 1 FROM ontology_link_types WHERE org_id = %s AND name = %s",
                (str(org_id), predicate),
            )
            if await cur.fetchone() is None:
                known = await self.list_link_types(org_id)
                names = [lt["name"] for lt in known]
                raise OntologyError(
                    f"Unknown link predicate '{predicate}'. Registered: {', '.join(names)}"
                )

    async def list_schema(self, org_id: UUID) -> dict[str, Any]:
        """Return link types, object kinds, interfaces, and action types."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT k.name, k.description, k.properties_schema,
                       COALESCE(array_agg(i.name ORDER BY i.name) FILTER (WHERE i.name IS NOT NULL), '{}')
                FROM ontology_object_kinds k
                LEFT JOIN ontology_kind_interfaces ki
                    ON ki.kind_id = k.id AND ki.org_id = k.org_id
                LEFT JOIN ontology_interfaces i ON i.id = ki.interface_id
                WHERE k.org_id = %s
                GROUP BY k.id, k.name, k.description, k.properties_schema
                ORDER BY k.name
                """,
                (str(org_id),),
            )
            kinds = [
                {
                    "name": r[0],
                    "description": r[1],
                    "properties_schema": r[2] or {},
                    "interfaces": list(r[3] or []),
                }
                for r in await cur.fetchall()
            ]
            cur = await conn.execute(
                """
                SELECT name, description, traits FROM ontology_interfaces
                WHERE org_id = %s ORDER BY name
                """,
                (str(org_id),),
            )
            interfaces = [
                {"name": r[0], "description": r[1], "traits": r[2] or []}
                for r in await cur.fetchall()
            ]
            cur = await conn.execute(
                """
                SELECT name, description, wrapper_tool, parameters_schema, requires_approval
                FROM ontology_action_types
                WHERE org_id = %s ORDER BY name
                """,
                (str(org_id),),
            )
            actions = [
                {
                    "name": r[0],
                    "description": r[1],
                    "wrapper_tool": r[2],
                    "parameters_schema": r[3] or {},
                    "requires_approval": r[4],
                }
                for r in await cur.fetchall()
            ]
        return {
            "link_types": await self.list_link_types(org_id),
            "object_kinds": kinds,
            "interfaces": interfaces,
            "action_types": actions,
        }

    async def get_action_type(self, org_id: UUID, name: str) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT id, name, description, wrapper_tool, parameters_schema, requires_approval
                FROM ontology_action_types
                WHERE org_id = %s AND name = %s
                """,
                (str(org_id), name),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "name": row[1],
            "description": row[2],
            "wrapper_tool": row[3],
            "parameters_schema": row[4] or {},
            "requires_approval": row[5],
        }

    def validate_action_parameters(
        self, action: dict[str, Any], parameters: dict[str, Any]
    ) -> None:
        schema = action.get("parameters_schema") or {}
        required = schema.get("required") or []
        missing = [k for k in required if k not in parameters or parameters[k] in (None, "")]
        if missing:
            raise OntologyError(f"Missing required parameters: {', '.join(missing)}")

    async def log_action(
        self,
        org_id: UUID,
        *,
        action_type_id: UUID,
        parameters: dict[str, Any],
        result: dict[str, Any] | None,
        status: str,
        actor: str,
        request_id: str | None = None,
    ) -> str:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                INSERT INTO ontology_action_log
                    (org_id, action_type_id, parameters, result, status, actor, request_id)
                VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                RETURNING id
                """,
                (
                    str(org_id),
                    str(action_type_id),
                    _json(parameters),
                    _json(result) if result is not None else None,
                    status,
                    actor,
                    request_id,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        return str(row[0])

    async def get_entity_by_slug(self, org_id: UUID, slug: str) -> dict[str, Any] | None:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT e.id, e.name, e.slug, e.properties, e.status, k.name,
                       COALESCE(array_agg(i.name ORDER BY i.name) FILTER (WHERE i.name IS NOT NULL), '{}')
                FROM ontology_entities e
                JOIN ontology_object_kinds k ON k.id = e.kind_id
                LEFT JOIN ontology_kind_interfaces ki
                    ON ki.kind_id = k.id AND ki.org_id = e.org_id
                LEFT JOIN ontology_interfaces i ON i.id = ki.interface_id
                WHERE e.org_id = %s AND e.slug = %s
                GROUP BY e.id, e.name, e.slug, e.properties, e.status, k.name
                """,
                (str(org_id), slug),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "name": row[1],
            "slug": row[2],
            "properties": row[3] or {},
            "status": row[4],
            "kind": row[5],
            "interfaces": list(row[6] or []),
        }

    async def propose_entity(
        self,
        org_id: UUID,
        *,
        kind_name: str,
        name: str,
        properties: dict[str, Any] | None,
        created_by: str,
        auto_approve: bool = False,
    ) -> dict[str, Any]:
        slug = slugify(name)
        status = "active" if auto_approve else "pending_approval"
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT id FROM ontology_object_kinds WHERE org_id = %s AND name = %s",
                (str(org_id), kind_name),
            )
            kind_row = await cur.fetchone()
            if kind_row is None:
                raise OntologyError(f"Unknown object kind '{kind_name}'")
            kind_id = kind_row[0]
            cur = await conn.execute(
                """
                INSERT INTO ontology_entities
                    (org_id, kind_id, name, slug, properties, status, created_by)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (org_id, slug) DO UPDATE SET
                    kind_id = EXCLUDED.kind_id,
                    name = EXCLUDED.name,
                    properties = EXCLUDED.properties,
                    status = EXCLUDED.status,
                    created_by = EXCLUDED.created_by
                RETURNING id, slug, status
                """,
                (
                    str(org_id), str(kind_id), name, slug,
                    _json(properties or {}), status, created_by,
                ),
            )
            row = await cur.fetchone()
        assert row is not None
        return {"entity_id": str(row[0]), "slug": row[1], "status": row[2], "kind": kind_name}

    async def list_by_interface(
        self, org_id: UUID, interface_name: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Return object kinds implementing an interface (P4 unified filters)."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT k.name, k.description
                FROM ontology_object_kinds k
                JOIN ontology_kind_interfaces ki ON ki.kind_id = k.id
                JOIN ontology_interfaces i ON i.id = ki.interface_id
                WHERE k.org_id = %s AND i.name = %s
                ORDER BY k.name
                LIMIT %s
                """,
                (str(org_id), interface_name, limit),
            )
            rows = await cur.fetchall()
        return [{"kind": r[0], "description": r[1]} for r in rows]

    async def list_action_log(
        self, org_id: UUID, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                """
                SELECT l.id, a.name, l.parameters, l.result, l.status, l.actor, l.created_at
                FROM ontology_action_log l
                JOIN ontology_action_types a ON a.id = l.action_type_id
                WHERE l.org_id = %s
                ORDER BY l.created_at DESC
                LIMIT %s
                """,
                (str(org_id), limit),
            )
            rows = await cur.fetchall()
        return [
            {
                "id": str(r[0]),
                "action_type": r[1],
                "parameters": r[2] or {},
                "result": r[3],
                "status": r[4],
                "actor": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]


def _json(value: Any) -> str:
    return json.dumps(value)
