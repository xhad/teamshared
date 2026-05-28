"""Best-effort audit log for sensitive memory operations."""

from __future__ import annotations

import json
from typing import Any

from psycopg_pool import AsyncConnectionPool

from teamshared.logging import get_logger

log = get_logger(__name__)


class AuditLog:
    """Append-only audit trail in Postgres ``audit_events``."""

    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def record(
        self,
        *,
        agent: str,
        action: str,
        target_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        try:
            async with self._pool.connection() as conn, conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO audit_events (agent, action, target_id, payload)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (agent, action, target_id, json.dumps(payload or {})),
                )
                await conn.commit()
        except Exception as exc:
            log.warning("audit_record_failed", action=action, error=str(exc))
