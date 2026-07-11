#!/usr/bin/env python3
"""Replay a private design-partner query fixture against a live MCP server."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from teamshared.memory.partner_eval import (
    load_partner_cases,
    score_partner_case,
    summarize_partner_results,
)


async def _run(url: str, token: str, fixture: Path) -> dict[str, Any]:
    cases = load_partner_cases(fixture)
    transport = StreamableHttpTransport(
        url, headers={"Authorization": f"Bearer {token}"}
    )
    results: list[dict[str, Any]] = []
    async with Client(transport) as client:
        for case in cases:
            response = await client.call_tool(
                "memory_recall",
                {
                    "query": case["query"],
                    "scope": case.get("scope"),
                    "k": int(case.get("k", 8)),
                    "explain": True,
                },
            )
            records = (response.data or {}).get("records") or []
            results.append(score_partner_case(case, records))
    return summarize_partner_results(results)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--url", required=True, help="MCP URL, e.g. https://teamshared.com/mcp")
    parser.add_argument("--token", required=True, help="Design-partner org tsk_ key")
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=0.8,
        help="Exit non-zero below this pass rate (default: 0.8)",
    )
    args = parser.parse_args()

    report = asyncio.run(_run(args.url, args.token, args.fixture))
    print(json.dumps(report, indent=2))
    return 0 if report["pass_rate"] >= args.min_pass_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
