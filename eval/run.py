"""Golden recall evaluation runner.

Walks `eval/golden.yaml`, writes each scenario's seeds via the live MCP
``memory_remember`` tool, then runs each probe through ``memory_recall`` and
checks the documented ``expect_any`` strings against the returned content.

Two run modes:

- Live HTTP (recommended). Requires a running ``teamshared serve`` and a token::

    export TEAMSHARED_EVAL_URL=http://localhost:8077/mcp/
    export TEAMSHARED_EVAL_TOKEN=teamshared_...
    python eval/run.py

- In-memory MCP without backing stores. The fake retriever is a simple
  bag-of-words match -- it sanity-checks the tool surface and lets the
  scenario file be linted in CI, but does NOT validate real semantic recall
  quality. Use the HTTP path for the real signal::

    python eval/run.py --in-memory

The script exits 0 only if every probe passes. Prints a per-scenario report.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


@dataclass
class ProbeResult:
    scenario: str
    query: str
    expected: list[str]
    got: list[str]
    passed: bool


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    data = yaml.safe_load(path.read_text())
    scenarios = data.get("scenarios") or []
    if not isinstance(scenarios, list):
        raise ValueError(f"{path}: top-level 'scenarios' must be a list")
    return scenarios


async def _seed(client: Client, agent: str, seeds: list[dict[str, Any]]) -> None:
    for seed in seeds:
        await client.call_tool(
            "memory_remember",
            {
                "content": seed["content"],
                "kind": seed.get("kind", "note"),
                "subject": seed.get("subject"),
                "tags": seed.get("tags") or [],
                "agent": agent,
            },
        )


async def _probe(client: Client, scenario: str, probe: dict[str, Any]) -> ProbeResult:
    query = probe["query"]
    expected = list(probe.get("expect_any") or [])
    recalled = await client.call_tool("memory_recall", {"query": query, "k": 8})
    records = recalled.data.get("records") or []
    contents = [str(r.get("content", "")) for r in records]
    haystack = " || ".join(contents).lower()
    passed = any(needle.lower() in haystack for needle in expected)
    return ProbeResult(
        scenario=scenario,
        query=query,
        expected=expected,
        got=contents[:3],
        passed=passed,
    )


async def _run(client: Client, scenarios: list[dict[str, Any]]) -> int:
    results: list[ProbeResult] = []
    for scenario in scenarios:
        name = scenario.get("name", "<unnamed>")
        print(f"\n=== {name} ===")
        await _seed(client, agent="eval", seeds=scenario.get("seeds") or [])
        for probe in scenario.get("probes") or []:
            result = await _probe(client, name, probe)
            results.append(result)
            mark = "PASS" if result.passed else "FAIL"
            print(f"  [{mark}] {result.query!r} -> expected one of {result.expected}")
            if not result.passed:
                for line in result.got:
                    print(f"          got: {line[:120]}")

    passed = sum(1 for r in results if r.passed)
    print(f"\n{passed}/{len(results)} probes passed")
    return 0 if passed == len(results) else 1


async def _main_http(url: str, token: str, scenarios_path: Path) -> int:
    transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
    async with Client(transport) as client:
        scenarios = _load_scenarios(scenarios_path)
        return await _run(client, scenarios)


async def _main_in_memory(scenarios_path: Path) -> int:
    from unittest.mock import AsyncMock, MagicMock

    from fastmcp import FastMCP

    from teamshared.config import Settings
    from teamshared.memory.recall import Recall
    from teamshared.memory.types import MemoryRecord
    from teamshared.server.state import ServerState, clear_state, set_state
    from teamshared.server.tools import register_tools

    mcp = FastMCP(name="teamshared-eval")
    register_tools(mcp)

    store: list[dict[str, Any]] = []

    async def fake_add(content: str, *, agent: str, pillar: str, **kwargs: Any) -> list[dict[str, Any]]:
        record = {"id": f"m-{len(store)}", "memory": content, "metadata": {"pillar": pillar, "agent": agent}}
        store.append(record)
        return [record]

    async def fake_search(query: str, **kwargs: Any) -> list[MemoryRecord]:
        terms = [t.lower() for t in query.lower().split() if len(t) > 2]
        out: list[MemoryRecord] = []
        for r in store:
            text = r["memory"].lower()
            hits = sum(1 for t in terms if t in text)
            if hits:
                out.append(
                    MemoryRecord(
                        id=r["id"],
                        pillar="semantic",
                        content=r["memory"],
                        agent=r["metadata"]["agent"],
                        score=hits / max(len(terms), 1),
                    )
                )
        out.sort(key=lambda x: x.score or 0, reverse=True)
        return out[: kwargs.get("limit", 8)]

    working = MagicMock()
    working.recent_records = AsyncMock(return_value=[])
    working.client = MagicMock()
    working.client.ping = AsyncMock(return_value=True)
    semantic = MagicMock()
    semantic.add = AsyncMock(side_effect=fake_add)
    semantic.search = AsyncMock(side_effect=fake_search)
    semantic._memory = object()
    procedural = MagicMock()
    procedural.search_procedures = AsyncMock(return_value=[])

    recall = Recall(working=working, semantic_episodic=semantic, procedural=procedural)
    audit = MagicMock()
    audit.record = AsyncMock()
    set_state(
        ServerState(
            settings=Settings(_env_file=None),
            tokens=MagicMock(),
            invites=MagicMock(),
            working=working,
            agent_state=MagicMock(),
            semantic_episodic=semantic,
            procedural=procedural,
            recall=recall,
            audit=audit,
            graph=None,
        )
    )

    try:
        async with Client(mcp) as client:
            scenarios = _load_scenarios(scenarios_path)
            return await _run(client, scenarios)
    finally:
        clear_state()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-memory", action="store_true")
    parser.add_argument(
        "--scenarios", type=Path, default=Path(__file__).parent / "golden.yaml"
    )
    args = parser.parse_args()

    if args.in_memory:
        sys.exit(asyncio.run(_main_in_memory(args.scenarios)))

    url = os.environ.get("TEAMSHARED_EVAL_URL")
    token = os.environ.get("TEAMSHARED_EVAL_TOKEN")
    if not (url and token):
        print("Missing TEAMSHARED_EVAL_URL / TEAMSHARED_EVAL_TOKEN (or pass --in-memory).")
        sys.exit(2)
    sys.exit(asyncio.run(_main_http(url, token, args.scenarios)))


if __name__ == "__main__":
    main()
