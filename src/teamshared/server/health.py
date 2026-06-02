"""Shared health probe used by HTTP ``/health`` and the MCP ``health`` tool."""

from __future__ import annotations

from typing import Any

import httpx

from teamshared import __version__
from teamshared.server.state import ServerState


def _is_healthy(value: str) -> bool:
    """A component is healthy if it is ``ok`` (optionally with a detail suffix,
    e.g. ``ok (model)``) or an intentionally-off optional dep (``disabled``)."""
    return value == "ok" or value.startswith("ok ") or value == "disabled"


async def check_components(state: ServerState) -> dict[str, Any]:
    """Return ``{"status", "version", "components": {...}}``.

    Probes every runtime dependency. Optional components (Neo4j, Ollama) report
    ``"disabled"`` when not configured, which does not degrade overall status.
    """
    settings = state.settings
    components: dict[str, str] = {}

    # This process answered the request, so the server itself is up.
    components["server"] = "ok"

    try:
        await state.working.client.ping()
        components["redis"] = "ok"
    except Exception as exc:
        components["redis"] = f"error: {exc}"

    try:
        async with state.services.tenant_db.admin() as conn:
            cur = await conn.execute("SELECT 1")
            await cur.fetchone()
        components["postgres"] = "ok"
    except Exception as exc:
        components["postgres"] = f"error: {exc}"

    # Semantic/episodic durable store (pgvector + embedder; this replaced Mem0).
    # The value carries the active embedder model.
    try:
        model = await state.services.vector_store.health(settings.default_org_id)
        components["semantic"] = f"ok ({model})"
    except Exception as exc:
        components["semantic"] = f"error: {exc}"

    # Distiller runs as a separate process; it stamps a short-TTL heartbeat in
    # Redis. A present key means it beat within the TTL window.
    try:
        beat = await state.working.last_heartbeat("distiller")
        components["distiller"] = "ok" if beat else "down"
    except Exception as exc:
        components["distiller"] = f"error: {exc}"

    # Curator runs as a separate process too (synthesizes the wiki); same
    # short-TTL heartbeat contract as the distiller.
    try:
        beat = await state.working.last_heartbeat("curator")
        components["curator"] = "ok" if beat else "down"
    except Exception as exc:
        components["curator"] = f"error: {exc}"

    if state.graph is not None:
        try:
            await state.graph.verify()
            components["graph"] = "ok"
        except Exception as exc:
            components["graph"] = f"error: {exc}"
    else:
        components["graph"] = "down"

    if settings.embed_provider == "ollama" or settings.llm_provider == "ollama":
        components["ollama"] = await _probe_ollama(settings)
    else:
        components["ollama"] = "disabled"

    overall = "ok" if all(_is_healthy(v) for v in components.values()) else "degraded"
    return {"status": overall, "version": __version__, "components": components}


async def _probe_ollama(settings: Any) -> str:
    """Confirm Ollama is reachable and report the model(s) teamshared runs on it."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags")
            resp.raise_for_status()
    except Exception as exc:
        return f"error: {exc}"
    roles: list[str] = []
    if settings.llm_provider == "ollama":
        roles.append(f"llm={settings.llm_model}")
    if settings.embed_provider == "ollama":
        roles.append(f"embed={settings.embed_model}")
    return f"ok ({', '.join(roles)})" if roles else "ok"
