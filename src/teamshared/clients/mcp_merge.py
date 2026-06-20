"""Merge teamshared into a JSON MCP client config (Cursor, Claude Desktop, etc.)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def merge_teamshared_mcp_config(
    config_path: Path,
    *,
    mcp_url: str,
    token: str,
) -> Path:
    """Add or update ``mcpServers.teamshared``; preserve other servers and top-level keys."""
    if config_path.is_file():
        try:
            data: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {config_path}: {exc}") from exc
    else:
        data = {}

    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object in {config_path}")

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError("mcpServers must be a JSON object")

    existing = servers.get("teamshared")
    if isinstance(existing, dict):
        headers = dict(existing.get("headers") or {})
        headers["Authorization"] = f"Bearer {token}"
        entry: dict[str, Any] = {**existing, "url": mcp_url, "headers": headers}
    else:
        entry = {
            "url": mcp_url,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    servers["teamshared"] = entry
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return config_path


def main(argv: list[str] | None = None) -> int:
    import os

    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: mcp_merge.py <config.json>", file=sys.stderr)
        return 2
    mcp_url = os.environ.get("TEAMSHARED_MCP_URL", "").strip()
    token = os.environ.get("TEAMSHARED_TOKEN", "").strip()
    if not mcp_url or not token:
        print("TEAMSHARED_MCP_URL and TEAMSHARED_TOKEN required", file=sys.stderr)
        return 2
    try:
        path = merge_teamshared_mcp_config(Path(args[0]), mcp_url=mcp_url, token=token)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
