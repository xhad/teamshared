"""Cross-agent recall smoke test.

Drives the MCP tool surface twice: once impersonating ``cursor``, once
impersonating ``hermes``. The cursor pass writes a few memories; the hermes
pass calls ``memory_recall`` and asserts it sees what cursor wrote.

This is the executable spec for the "shared brain" claim in README.md. The
in-memory mock honors the per-agent filter that ``Recall.search`` passes
down — so if anyone reintroduces the old "default to caller's identity on
read" behavior, hermes will only see hermes' writes and this smoke fails.

Run mode 1 -- against a live HTTP server (recommended):

    actx token mint cursor
    actx token mint hermes
    # Paste the tokens into env:
    export ACTX_SMOKE_URL=http://localhost:8077/mcp/
    export ACTX_SMOKE_TOKEN_CURSOR=actx_...
    export ACTX_SMOKE_TOKEN_HERMES=actx_...
    python scripts/smoke_cross_agent.py

Run mode 2 -- in-memory (no server, mocked stores). Useful for CI:

    python scripts/smoke_cross_agent.py --in-memory
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def _drive_agent(
    client: Client,
    agent_label: str,
    *,
    inject_agent: bool = False,
    extra_recall_args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call the canonical sequence of memory tools and return the recall payload.

    When ``inject_agent`` is true we explicitly pass ``agent=<label>`` on every
    write tool. Live HTTP mode doesn't need this (the bearer token resolves
    identity); the in-memory mode does, because there's no auth middleware to
    bind a context identity.
    """
    write_extra = {"agent": agent_label} if inject_agent else {}

    print(f"[{agent_label}] memory_session_open ...")
    opened = await client.call_tool(
        "memory_session_open", {"topic": "smoke test", **write_extra}
    )
    session_id = opened.data["session_id"]

    print(f"[{agent_label}] memory_session_append x2 ...")
    await client.call_tool(
        "memory_session_append",
        {"session_id": session_id, "role": "user", "content": "I prefer pgvector over Pinecone."},
    )
    await client.call_tool(
        "memory_session_append",
        {
            "session_id": session_id,
            "role": "assistant",
            "content": "Noted. I'll default to pgvector going forward.",
        },
    )

    print(f"[{agent_label}] memory_remember (preference) ...")
    await client.call_tool(
        "memory_remember",
        {
            "content": f"{agent_label} noted: user prefers pgvector for vector storage.",
            "kind": "preference",
            "subject": "user",
            "tags": ["preference", "vectordb"],
            **write_extra,
        },
    )

    print(f"[{agent_label}] memory_session_close ...")
    closed = await client.call_tool(
        "memory_session_close", {"session_id": session_id, "distill": False}
    )

    print(f"[{agent_label}] memory_recall ('vector db preference') ...")
    recall_args: dict[str, Any] = {"query": "vector database preference", "k": 5}
    if extra_recall_args:
        recall_args.update(extra_recall_args)
    recalled = await client.call_tool("memory_recall", recall_args)
    return {"closed": closed.data, "recall": recalled.data}


async def _run_in_memory() -> int:
    from unittest.mock import AsyncMock, MagicMock

    from fastmcp import FastMCP

    from actx.config import Settings
    from actx.memory.recall import Recall
    from actx.memory.types import MemoryRecord
    from actx.server.state import ServerState, clear_state, set_state
    from actx.server.tools import register_tools

    mcp = FastMCP(name="actx-smoke")
    register_tools(mcp)

    seen_writes: list[dict[str, Any]] = []

    working = MagicMock()
    working.open_session = AsyncMock(return_value="sess_smoke")
    working.append_turn = AsyncMock(return_value=1)
    working.close_session = AsyncMock(
        return_value={"session_id": "sess_smoke", "turn_count": 2, "closed_at": "now", "distill_enqueued": False}
    )
    working.recent_records = AsyncMock(return_value=[])
    working.client = MagicMock()
    working.client.ping = AsyncMock(return_value=True)

    async def fake_add(content: str, *, agent: str, pillar: str, **kwargs: Any) -> list[dict[str, Any]]:
        record = {
            "id": f"mem-{len(seen_writes)}",
            "memory": content,
            "metadata": {"pillar": pillar, "agent": agent, **kwargs.get("extra_metadata", {})},
        }
        seen_writes.append(record)
        return [record]

    semantic = MagicMock()
    semantic.add = AsyncMock(side_effect=fake_add)
    semantic.list_episodes = AsyncMock(return_value=[])
    semantic.delete = AsyncMock(return_value=True)
    semantic._memory = object()

    async def fake_search(query: str, **kwargs: Any) -> list[MemoryRecord]:
        agent_filter: str | None = kwargs.get("agent")
        matches = [
            w
            for w in seen_writes
            if "vector" in w["memory"].lower() or "pgvector" in w["memory"].lower()
        ]
        if agent_filter is not None:
            matches = [w for w in matches if w["metadata"]["agent"] == agent_filter]
        return [
            MemoryRecord(
                id=w["id"],
                pillar="semantic",
                content=w["memory"],
                agent=w["metadata"]["agent"],
                score=0.9,
            )
            for w in matches
        ]

    semantic.search = AsyncMock(side_effect=fake_search)

    procedural = MagicMock()
    procedural.search_procedures = AsyncMock(return_value=[])

    recall = Recall(working=working, semantic_episodic=semantic, procedural=procedural)
    set_state(
        ServerState(
            settings=Settings(_env_file=None),
            tokens=MagicMock(),
            working=working,
            semantic_episodic=semantic,
            procedural=procedural,
            recall=recall,
            graph=None,
        )
    )

    try:
        async with Client(mcp) as cursor_client:
            cursor_result = await _drive_agent(
                cursor_client, "cursor", inject_agent=True
            )
        async with Client(mcp) as hermes_client:
            hermes_result = await _drive_agent(
                hermes_client, "hermes", inject_agent=True
            )
        # Bonus: prove that opt-in scoping still works — hermes asks for
        # cursor-only and gets only cursor's writes.
        async with Client(mcp) as hermes_client:
            scoped_result = await _drive_agent(
                hermes_client,
                "hermes",
                inject_agent=True,
                extra_recall_args={"agent": "cursor"},
            )
    finally:
        clear_state()

    cursor_records = cursor_result["recall"]["records"]
    hermes_records = hermes_result["recall"]["records"]
    scoped_records = scoped_result["recall"]["records"]

    print()
    print(f"cursor saw {len(cursor_records)} record(s) on recall (default = shared)")
    print(f"hermes saw {len(hermes_records)} record(s) on recall (default = shared)")
    print(f"hermes saw {len(scoped_records)} record(s) on recall (scoped to cursor)")

    cursor_writes = [w for w in seen_writes if w["metadata"]["agent"] == "cursor"]
    hermes_writes = [w for w in seen_writes if w["metadata"]["agent"] == "hermes"]
    if not (cursor_writes and hermes_writes):
        print("FAIL: expected writes from both agents")
        return 2

    if not any("cursor noted" in r["content"].lower() for r in hermes_records):
        print("FAIL: hermes did not see cursor's pgvector preference (shared brain broken)")
        return 1

    scoped_authors = {r.get("agent") for r in scoped_records}
    if scoped_authors != {"cursor"}:
        print(
            f"FAIL: agent='cursor' filter leaked other agents' writes: {scoped_authors!r}"
        )
        return 1

    print("OK: shared memory works across agents, and explicit agent= still filters")
    return 0


async def _run_http(url: str, cursor_token: str, hermes_token: str) -> int:
    transport_cursor = StreamableHttpTransport(
        url, headers={"Authorization": f"Bearer {cursor_token}"}
    )
    transport_hermes = StreamableHttpTransport(
        url, headers={"Authorization": f"Bearer {hermes_token}"}
    )

    async with Client(transport_cursor) as cursor_client:
        cursor_result = await _drive_agent(cursor_client, "cursor")
    async with Client(transport_hermes) as hermes_client:
        hermes_result = await _drive_agent(hermes_client, "hermes")
    async with Client(transport_hermes) as hermes_client:
        scoped_result = await _drive_agent(
            hermes_client, "hermes", extra_recall_args={"agent": "cursor"}
        )

    cursor_records = cursor_result["recall"]["records"]
    hermes_records = hermes_result["recall"]["records"]
    scoped_records = scoped_result["recall"]["records"]

    print()
    print(f"cursor saw {len(cursor_records)} record(s) on recall (default = shared)")
    print(f"hermes saw {len(hermes_records)} record(s) on recall (default = shared)")
    print(f"hermes saw {len(scoped_records)} record(s) on recall (scoped to cursor)")

    if not any(
        (r.get("agent") == "cursor" and "pgvector" in r.get("content", "").lower())
        for r in hermes_records
    ):
        print("FAIL: hermes did not see cursor's pgvector preference (shared brain broken)")
        return 1

    scoped_authors = {r.get("agent") for r in scoped_records if r.get("agent")}
    if scoped_authors and scoped_authors != {"cursor"}:
        print(
            f"FAIL: agent='cursor' filter leaked other agents' writes: {scoped_authors!r}"
        )
        return 1

    print("OK: shared memory works across agents, and explicit agent= still filters")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-memory", action="store_true", help="Run without a live server")
    args = parser.parse_args()

    if args.in_memory:
        rc = asyncio.run(_run_in_memory())
        sys.exit(rc)

    url = os.environ.get("ACTX_SMOKE_URL")
    cursor_token = os.environ.get("ACTX_SMOKE_TOKEN_CURSOR")
    hermes_token = os.environ.get("ACTX_SMOKE_TOKEN_HERMES")
    if not (url and cursor_token and hermes_token):
        print(
            "Missing ACTX_SMOKE_URL / ACTX_SMOKE_TOKEN_CURSOR / ACTX_SMOKE_TOKEN_HERMES "
            "(or pass --in-memory)."
        )
        sys.exit(2)
    rc = asyncio.run(_run_http(url, cursor_token, hermes_token))
    sys.exit(rc)


if __name__ == "__main__":
    main()
