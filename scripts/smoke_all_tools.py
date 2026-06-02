"""Exercise every teamshared MCP tool against a live server.

Runs a ordered checklist: health, procedures, semantic/episodic writes,
sessions, recall (including pre-existing memories), episodes list, graph,
client state, and optional forget cleanup.

Live HTTP (recommended — hits real Postgres, Redis, Mem0):

    export TEAMSHARED_SMOKE_URL=https://teamshared.com/mcp/
    export TEAMSHARED_SMOKE_TOKEN=tsk_...
    python scripts/smoke_all_tools.py

Local stack:

    export TEAMSHARED_SMOKE_URL=http://localhost:8077/mcp/
    export TEAMSHARED_SMOKE_TOKEN=$(make token-mint 2>/dev/null | tail -1)
    python scripts/smoke_all_tools.py

Cross-agent shared-brain check (optional second token):

    export TEAMSHARED_SMOKE_TOKEN_HERMES=tsk_...
    python scripts/smoke_all_tools.py

In-memory mode registers tools with mocked stores — structure only, not recall quality:

    python scripts/smoke_all_tools.py --in-memory
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


@dataclass
class StepResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class SmokeReport:
    steps: list[StepResult] = field(default_factory=list)

    def ok(self, name: str, detail: str = "") -> None:
        self.steps.append(StepResult(name, True, detail))

    def fail(self, name: str, detail: str) -> None:
        self.steps.append(StepResult(name, False, detail))

    @property
    def passed(self) -> bool:
        return all(s.passed for s in self.steps)


def _record_text(records: list[dict[str, Any]]) -> str:
    return " || ".join(str(r.get("content", "")) for r in records).lower()


async def _call(client: Client, tool: str, args: dict[str, Any] | None = None) -> Any:
    result = await client.call_tool(tool, args or {})
    return result.data


async def _run_live(
    url: str,
    token: str,
    *,
    hermes_token: str | None,
    repo_slug: str,
    skip_forget: bool,
    existing_queries: list[tuple[str, list[str]]],
) -> SmokeReport:
    report = SmokeReport()
    run_id = uuid.uuid4().hex[:8]
    marker = f"smoke-all-tools-{run_id}"
    proc_name = f"teamshared.smoke-{run_id}"
    state_key = f"smoke-all-tools/{run_id}"

    transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
    async with Client(transport) as client:
        # --- health ---
        print("[1/15] health")
        health = await _call(client, "health")
        if health.get("status") == "ok" and all(v == "ok" for v in health.get("components", {}).values()):
            report.ok("health", str(health.get("components")))
        else:
            report.fail("health", str(health))

        # --- procedures (existing + write) ---
        print("[2/15] memory_procedures_list (seeded playbooks)")
        listed = await _call(client, "memory_procedures_list", {"limit": 50})
        proc_count = listed.get("count", 0)
        if proc_count >= 1:
            report.ok("memory_procedures_list", f"{proc_count} procedure(s)")
        else:
            report.fail("memory_procedures_list", f"expected >=1, got {proc_count}")

        print("[3/15] memory_procedure_get (teamshared.start-of-task)")
        got_proc = await _call(client, "memory_procedure_get", {"name": "teamshared.start-of-task"})
        if got_proc and got_proc.get("name") == "teamshared.start-of-task":
            report.ok("memory_procedure_get", f"v{got_proc.get('version')}")
        else:
            report.fail("memory_procedure_get", str(got_proc))

        print(f"[4/15] memory_procedure_set ({proc_name})")
        created = await _call(
            client,
            "memory_procedure_set",
            {
                "name": proc_name,
                "description": f"Smoke test procedure {run_id}",
                "steps_md": f"# Smoke\n\n1. Marker `{marker}`\n",
                "tags": ["smoke", "ephemeral"],
            },
        )
        if created and created.get("name") == proc_name:
            report.ok("memory_procedure_set", f"v{created.get('version')}")
        else:
            report.fail("memory_procedure_set", str(created))

        print("[5/15] memory_recall (procedural — seeded + new)")
        proc_recall = await _call(
            client,
            "memory_recall",
            {"query": "start of task ritual smoke", "scope": ["procedural"], "k": 10},
        )
        proc_hay = _record_text(proc_recall.get("records") or [])
        if "start-of-task" in proc_hay or proc_name.replace("teamshared.", "") in proc_hay:
            report.ok("memory_recall/procedural", f"{proc_recall.get('counts_by_pillar')}")
        else:
            report.fail("memory_recall/procedural", f"records={proc_recall.get('records')}")

        # --- semantic / episodic writes ---
        print(f"[6/15] memory_remember (semantic marker {marker})")
        remembered = await _call(
            client,
            "memory_remember",
            {
                "content": f"{marker}: user prefers integration smoke tests before deploy.",
                "kind": "preference",
                "subject": "user",
                "tags": ["smoke", marker],
            },
        )
        mem_ids: list[str] = []
        for item in remembered.get("stored") or []:
            if item.get("id"):
                mem_ids.append(str(item["id"]))
        if remembered.get("count", 0) >= 1:
            report.ok("memory_remember/semantic", f"stored {remembered.get('count')} chunk(s)")
        else:
            report.fail("memory_remember/semantic", str(remembered))

        print(f"[7/15] memory_remember (episodic event {marker})")
        event = await _call(
            client,
            "memory_remember",
            {
                "content": f"{marker}: episodic smoke event logged for tool verification.",
                "kind": "event",
                "tags": ["smoke", marker],
            },
        )
        for item in event.get("stored") or []:
            if item.get("id"):
                mem_ids.append(str(item["id"]))
        if event.get("pillar") == "episodic":
            report.ok("memory_remember/episodic", f"stored {event.get('count')} chunk(s)")
        else:
            report.fail("memory_remember/episodic", str(event))

        # --- working memory session ---
        print("[8/15] memory_session_open / append / close")
        opened = await _call(client, "memory_session_open", {"topic": f"smoke {marker}"})
        session_id = opened.get("session_id")
        if not session_id:
            report.fail("memory_session_open", str(opened))
        else:
            report.ok("memory_session_open", session_id)
            appended = await _call(
                client,
                "memory_session_append",
                {
                    "session_id": session_id,
                    "role": "user",
                    "content": f"Session turn mentions {marker} and pgvector.",
                },
            )
            if appended.get("turn_count", 0) >= 1:
                report.ok("memory_session_append", f"turns={appended['turn_count']}")
            else:
                report.fail("memory_session_append", str(appended))

            working_recall = await _call(
                client,
                "memory_recall",
                {"query": marker, "scope": ["working"], "k": 5},
            )
            working_hay = _record_text(working_recall.get("records") or [])
            if marker in working_hay or "pgvector" in working_hay:
                report.ok("memory_recall/working", f"{working_recall.get('counts_by_pillar')}")
            else:
                report.fail("memory_recall/working", f"records={working_recall.get('records')}")

            closed = await _call(
                client, "memory_session_close", {"session_id": session_id, "distill": False}
            )
            if closed.get("session_id") == session_id:
                report.ok("memory_session_close", f"turns={closed.get('turn_count')}")
            else:
                report.fail("memory_session_close", str(closed))

        # --- recall new + existing ---
        print(f"[9/15] memory_recall (new write — {marker})")
        # Mem0 extraction can lag briefly; retry a few times.
        fresh_hay = ""
        for attempt in range(5):
            fresh = await _call(client, "memory_recall", {"query": marker, "k": 10})
            fresh_hay = _record_text(fresh.get("records") or [])
            if marker in fresh_hay or "integration smoke tests" in fresh_hay:
                report.ok("memory_recall/new-write", f"attempt={attempt + 1}")
                break
            await asyncio.sleep(1.0)
        else:
            report.fail("memory_recall/new-write", f"records={fresh.get('records')}")

        print("[10/15] memory_recall (pre-existing memories)")
        existing_ok = True
        existing_details: list[str] = []
        for label, needles in existing_queries:
            recalled = await _call(client, "memory_recall", {"query": label, "k": 10})
            hay = _record_text(recalled.get("records") or [])
            if any(n.lower() in hay for n in needles):
                existing_details.append(f"{label}: hit")
            else:
                existing_ok = False
                existing_details.append(f"{label}: miss (need one of {needles!r})")
        if existing_ok:
            report.ok("memory_recall/existing", "; ".join(existing_details))
        else:
            report.fail("memory_recall/existing", "; ".join(existing_details))

        print("[11/15] memory_episodes_list")
        episodes = await _call(client, "memory_episodes_list", {"limit": 20})
        if "count" in episodes and "episodes" in episodes:
            report.ok("memory_episodes_list", f"count={episodes['count']}")
        else:
            report.fail("memory_episodes_list", str(episodes))

        # --- graph (optional) ---
        print("[12/15] memory_graph_relate / memory_graph_related")
        related_write = await _call(
            client,
            "memory_graph_relate",
            {"subject": marker, "predicate": "smoke_tested_by", "object": "teamshared"},
        )
        if related_write.get("ok") is True:
            report.ok("memory_graph_relate", "graph enabled")
            graph_read = await _call(client, "memory_graph_related", {"name": marker, "depth": 1})
            if graph_read.get("count", 0) >= 1:
                report.ok("memory_graph_related", f"count={graph_read['count']}")
            else:
                report.fail("memory_graph_related", str(graph_read))
        elif related_write.get("reason") == "graph_disabled":
            graph_read = await _call(client, "memory_graph_related", {"name": marker})
            if graph_read.get("reason") == "graph_disabled":
                report.ok("memory_graph_relate", "graph_disabled (expected)")
                report.ok("memory_graph_related", "graph_disabled (expected)")
            else:
                report.fail("memory_graph_related", str(graph_read))
        else:
            report.fail("memory_graph_relate", str(related_write))

        # --- client state ---
        print("[13/15] memory_state_set / memory_state_get")
        state_value = {"version": 1, "marker": marker, "at": time.time()}
        await _call(
            client,
            "memory_state_set",
            {"repo": repo_slug, "key": state_key, "value": state_value},
        )
        state_read = await _call(
            client, "memory_state_get", {"repo": repo_slug, "key": state_key}
        )
        if state_read.get("value") == state_value:
            report.ok("memory_state_set/get", state_key)
        else:
            report.fail("memory_state_set/get", str(state_read))

        # --- forget (optional cleanup) ---
        forget_id = mem_ids[0] if mem_ids else None
        if skip_forget:
            print("[14/15] memory_forget (skipped)")
            report.ok("memory_forget", "skipped via --skip-forget")
        elif forget_id:
            print(f"[14/15] memory_forget ({forget_id[:8]}…)")
            forgot = await _call(
                client,
                "memory_forget",
                {"memory_id": forget_id, "reason": f"smoke_all_tools cleanup {run_id}"},
            )
            if forgot.get("deleted"):
                report.ok("memory_forget", forget_id[:12])
            else:
                report.fail("memory_forget", str(forgot))
        else:
            print("[14/15] memory_forget (no id captured)")
            report.fail("memory_forget", "no memory_id from memory_remember")

        # --- cross-agent (optional) ---
        print("[15/15] cross-agent shared brain (optional)")
        if hermes_token:
            hermes_transport = StreamableHttpTransport(
                url, headers={"Authorization": f"Bearer {hermes_token}"}
            )
            async with Client(hermes_transport) as hermes_client:
                hermes_recall = await _call(
                    hermes_client,
                    "memory_recall",
                    {"query": marker, "k": 10},
                )
                hay = _record_text(hermes_recall.get("records") or [])
                if marker in hay or "integration smoke tests" in hay:
                    report.ok("cross-agent recall", "hermes sees cursor write")
                else:
                    report.fail(
                        "cross-agent recall",
                        f"hermes did not see {marker!r}: {hermes_recall.get('records')}",
                    )
        else:
            report.ok("cross-agent recall", "skipped (set TEAMSHARED_SMOKE_TOKEN_HERMES)")

    return report


async def _run_in_memory() -> SmokeReport:
    from unittest.mock import AsyncMock, MagicMock

    from fastmcp import FastMCP

    from teamshared.config import Settings
    from teamshared.memory.recall import Recall
    from teamshared.memory.types import MemoryRecord
    from teamshared.server.state import ServerState, clear_state, set_state
    from teamshared.server.tools import register_tools

    report = SmokeReport()
    mcp = FastMCP(name="teamshared-smoke-all")
    register_tools(mcp)

    working = MagicMock()
    working.open_session = AsyncMock(return_value="sess_smoke")
    working.append_turn = AsyncMock(return_value=1)
    working.close_session = AsyncMock(
        return_value={
            "session_id": "sess_smoke",
            "turn_count": 1,
            "closed_at": "now",
            "distill_enqueued": False,
        }
    )
    working.recent_records = AsyncMock(
        return_value=[
            MemoryRecord(
                id="w1",
                pillar="working",
                content="working turn pgvector",
                agent="cursor",
                score=1.0,
            )
        ]
    )
    working.client = MagicMock()
    working.client.ping = AsyncMock(return_value=True)

    semantic = MagicMock()
    semantic.add = AsyncMock(
        return_value=[{"id": "m1", "memory": "stored", "metadata": {"pillar": "semantic"}}]
    )
    semantic.list_episodes = AsyncMock(return_value=[])
    semantic.delete = AsyncMock(return_value=True)
    semantic._memory = object()

    async def fake_search(query: str, **kwargs: Any) -> list[MemoryRecord]:
        return [
            MemoryRecord(
                id="s1",
                pillar="semantic",
                content=f"answer for {query}",
                agent="cursor",
                score=0.9,
            )
        ]

    semantic.search = AsyncMock(side_effect=fake_search)

    procedural = MagicMock()
    procedural.get_procedure = AsyncMock(
        return_value={
            "id": 1,
            "name": "teamshared.start-of-task",
            "version": 1,
            "description": "x",
            "steps_md": "steps",
            "tool_recipe": None,
            "tags": [],
            "created_by": "teamshared",
            "created_at": None,
        }
    )
    procedural.set_procedure = AsyncMock(
        return_value={
            "id": 2,
            "name": "teamshared.smoke",
            "version": 1,
            "description": "smoke",
            "steps_md": "steps",
            "tool_recipe": None,
            "tags": ["smoke"],
            "created_by": "cursor",
            "created_at": None,
        }
    )
    procedural.list_procedures = AsyncMock(
        return_value=[
            {
                "id": 1,
                "name": "teamshared.start-of-task",
                "version": 1,
                "description": "x",
                "steps_md": "steps",
                "tool_recipe": None,
                "tags": [],
                "created_by": "teamshared",
                "created_at": None,
            }
        ]
    )
    procedural.search_procedures = AsyncMock(
        return_value=[
            MemoryRecord(
                id="1",
                pillar="procedural",
                content="teamshared.start-of-task (v1): preamble",
                agent="teamshared",
                score=0.8,
            )
        ]
    )
    pool_ctx = MagicMock()
    pool_ctx.__aenter__ = AsyncMock(return_value=pool_ctx)
    pool_ctx.__aexit__ = AsyncMock(return_value=False)
    pool_ctx.cursor = MagicMock(return_value=pool_ctx)
    pool_ctx.execute = AsyncMock()
    pool_ctx.fetchone = AsyncMock(return_value=(1,))
    procedural.pool = MagicMock()
    procedural.pool.connection = MagicMock(return_value=pool_ctx)

    recall = Recall(working=working, semantic_episodic=semantic, procedural=procedural)
    agent_state = MagicMock()
    stored_state: dict[tuple[str, str, str], dict[str, Any]] = {}

    async def fake_get(state_id: str, repo: str, key: str) -> dict[str, Any] | None:
        return stored_state.get((state_id, repo, key))

    async def fake_set(state_id: str, repo: str, key: str, value: dict[str, Any]) -> None:
        stored_state[(state_id, repo, key)] = value

    agent_state.get = AsyncMock(side_effect=fake_get)
    agent_state.set = AsyncMock(side_effect=fake_set)

    audit = MagicMock()
    audit.record = AsyncMock()
    semantic.is_ready = True
    working.get_metadata = AsyncMock(return_value={"agent": "cursor"})

    set_state(
        ServerState(
            settings=Settings(_env_file=None),
            invites=MagicMock(),
            working=working,
            agent_state=agent_state,
            semantic_episodic=semantic,
            procedural=procedural,
            recall=recall,
            audit=audit,
            graph=None,
        )
    )

    from teamshared.auth import AgentIdentity, _current_agent

    auth_token = _current_agent.set(AgentIdentity(agent="cursor", state_id="smoke_test"))

    try:
        async with Client(mcp) as client:
            for tool, args, name in [
                ("health", {}, "health"),
                ("memory_procedures_list", {"limit": 5}, "memory_procedures_list"),
                ("memory_procedure_get", {"name": "teamshared.start-of-task"}, "memory_procedure_get"),
                (
                    "memory_procedure_set",
                    {"name": "p", "steps_md": "# x"},
                    "memory_procedure_set",
                ),
                ("memory_recall", {"query": "task", "scope": ["procedural"]}, "memory_recall"),
                ("memory_remember", {"content": "x", "kind": "note"}, "memory_remember"),
                ("memory_session_open", {"topic": "t"}, "memory_session_open"),
            ]:
                data = await _call(client, tool, args)
                if data is not None:
                    report.ok(name, "reachable")
                else:
                    report.fail(name, "empty response")

            opened = await _call(client, "memory_session_open", {"topic": "t"})
            sid = opened["session_id"]
            await _call(
                client,
                "memory_session_append",
                {"session_id": sid, "role": "user", "content": "hi"},
            )
            await _call(client, "memory_session_close", {"session_id": sid, "distill": False})
            report.ok("memory_session_append/close", sid)

            episodes = await _call(client, "memory_episodes_list", {"limit": 5})
            report.ok("memory_episodes_list", str(episodes.get("count")))

            graph = await _call(
                client,
                "memory_graph_relate",
                {"subject": "a", "predicate": "b", "object": "c"},
            )
            if graph.get("reason") == "graph_disabled":
                report.ok("memory_graph_relate", "graph_disabled")
            else:
                report.fail("memory_graph_relate", str(graph))

            await _call(
                client,
                "memory_state_set",
                {"repo": "test-repo", "key": "k", "value": {"v": 1}},
            )
            got = await _call(client, "memory_state_get", {"repo": "test-repo", "key": "k"})
            if got.get("value") == {"v": 1}:
                report.ok("memory_state_set/get", "roundtrip")
            else:
                report.fail("memory_state_set/get", str(got))

            forgot = await _call(
                client,
                "memory_forget",
                {"memory_id": "m1", "reason": "smoke"},
            )
            if forgot.get("deleted"):
                report.ok("memory_forget", "m1")
            else:
                report.fail("memory_forget", str(forgot))
    finally:
        _current_agent.reset(auth_token)
        clear_state()

    report.ok("cross-agent recall", "skipped in --in-memory mode")
    return report


def _print_report(report: SmokeReport) -> int:
    print()
    print("=" * 60)
    print("SMOKE REPORT")
    print("=" * 60)
    for step in report.steps:
        mark = "PASS" if step.passed else "FAIL"
        suffix = f" — {step.detail}" if step.detail else ""
        print(f"  [{mark}] {step.name}{suffix}")
    print("=" * 60)
    passed = sum(1 for s in report.steps if s.passed)
    total = len(report.steps)
    print(f"{passed}/{total} steps passed")
    if report.passed:
        print("OK: all teamshared MCP tools exercised successfully")
        return 0
    print("FAIL: one or more steps failed")
    return 1


def _normalize_mcp_url(url: str) -> str:
    url = url.rstrip("/")
    if url.endswith("/mcp"):
        return url + "/"
    if not url.endswith("/mcp/"):
        return url + "/mcp/"
    return url


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test every teamshared MCP tool.")
    parser.add_argument("--in-memory", action="store_true", help="Mocked stores (structure only)")
    parser.add_argument("--url", default=os.environ.get("TEAMSHARED_SMOKE_URL"))
    parser.add_argument("--token", default=os.environ.get("TEAMSHARED_SMOKE_TOKEN"))
    parser.add_argument(
        "--hermes-token",
        default=os.environ.get("TEAMSHARED_SMOKE_TOKEN_HERMES"),
        help="Optional second token for cross-agent recall check",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get(
            "TEAMSHARED_SMOKE_REPO", "Users-chad-code-sapien-teamshared"
        ),
        help="Workspace slug for memory_state_* tests",
    )
    parser.add_argument(
        "--skip-forget",
        action="store_true",
        help="Do not call memory_forget (leaves smoke memories in the brain)",
    )
    parser.add_argument(
        "--expect-existing",
        action="append",
        metavar="QUERY:NEEDLE1,NEEDLE2",
        help=(
            "Recall probe for pre-existing memory. Repeatable. "
            "Example: --expect-existing 'smoke test:smoke-test,production health'"
        ),
    )
    args = parser.parse_args()

    existing_queries: list[tuple[str, list[str]]] = [
        ("smoke test production health", ["smoke-test", "production health"]),
        ("start of task ritual", ["start-of-task"]),
    ]
    for raw in args.expect_existing or []:
        if ":" not in raw:
            print(f"Invalid --expect-existing (need QUERY:NEEDLE,...): {raw!r}")
            sys.exit(2)
        query, needles = raw.split(":", 1)
        existing_queries.append((query.strip(), [n.strip() for n in needles.split(",") if n.strip()]))

    if args.in_memory:
        rc = asyncio.run(_run_in_memory())
        sys.exit(_print_report(rc))

    if not (args.url and args.token):
        print(
            "Missing --url/--token or TEAMSHARED_SMOKE_URL / TEAMSHARED_SMOKE_TOKEN "
            "(or pass --in-memory)."
        )
        sys.exit(2)

    report = asyncio.run(
        _run_live(
            _normalize_mcp_url(args.url),
            args.token,
            hermes_token=args.hermes_token,
            repo_slug=args.repo,
            skip_forget=args.skip_forget,
            existing_queries=existing_queries,
        )
    )
    sys.exit(_print_report(report))


if __name__ == "__main__":
    main()
