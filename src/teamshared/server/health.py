"""Shared health probe used by HTTP ``/health`` and the MCP ``health`` tool."""

from __future__ import annotations

from typing import Any

from teamshared.server.state import ServerState


async def check_components(state: ServerState) -> dict[str, Any]:
    """Return ``{"status": "ok"|"degraded", "components": {...}}``."""
    components: dict[str, str] = {}
    try:
        await state.working.client.ping()
        components["redis"] = "ok"
    except Exception as exc:
        components["redis"] = f"error: {exc}"

    try:
        async with state.procedural.pool.connection() as conn, conn.cursor() as cur:
            await cur.execute("SELECT 1")
            await cur.fetchone()
        components["postgres"] = "ok"
    except Exception as exc:
        components["postgres"] = f"error: {exc}"

    components["mem0"] = "ok" if state.semantic_episodic.is_ready else "not_ready"

    overall = "ok" if all(v == "ok" for v in components.values()) else "degraded"
    return {"status": overall, "components": components}
