#!/usr/bin/env python3
"""teamshared conversation-capture shell hook for the Hermes agent.

Registered on the ``post_llm_call`` event in ``~/.hermes/config.yaml`` (see
``hooks.yaml``). Hermes fires this event once per turn, piping a JSON payload to
stdin whose ``extra`` dict carries ``user_message`` and ``assistant_response``.
This script forwards those turns to teamshared's ``POST /sessions/turns`` sink,
which lands them in the caller's rolling per-agent working session — the same
session the server-side tool-call capture writes to.

Stdlib only (urllib/json): the hook runs via the system ``python3`` as a
subprocess, so it must not depend on PyYAML, requests, or httpx.

Capture is best-effort: any failure is swallowed and an empty ``{}`` is written
to stdout so the hook never blocks or aborts the Hermes agent loop.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

MAX_TURN_CHARS = 8000
CREDS_FILE = Path.home() / ".hermes" / "agent-hooks" / "teamshared-capture.json"
HERMES_CONFIG = Path.home() / ".hermes" / "config.yaml"


def _normalize_base(url: str) -> str:
    url = url.strip().rstrip("/")
    if url.endswith("/mcp"):
        url = url[: -len("/mcp")]
    return url


def _creds_from_env() -> tuple[str, str] | None:
    base = os.environ.get("TEAMSHARED_STATE_URL") or os.environ.get("TEAMSHARED_URL")
    token = os.environ.get("TEAMSHARED_STATE_TOKEN") or os.environ.get("TEAMSHARED_TOKEN")
    if base and token:
        return _normalize_base(base), token.strip()
    return None


def _creds_from_file() -> tuple[str, str] | None:
    try:
        data = json.loads(CREDS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    base = data.get("base_url") or data.get("url")
    token = data.get("token")
    if isinstance(base, str) and isinstance(token, str) and base and token:
        return _normalize_base(base), token.strip()
    return None


def _creds_from_config() -> tuple[str, str] | None:
    """Best-effort line parse of the teamshared block in ~/.hermes/config.yaml.

    Avoids a PyYAML dependency; only needs the ``url`` and ``Authorization``
    lines under ``mcp_servers.teamshared``.
    """
    try:
        lines = HERMES_CONFIG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    in_block = False
    base: str | None = None
    token: str | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("teamshared:"):
            in_block = True
            continue
        if in_block:
            # A non-indented, non-empty line ends the block.
            if line and not line[0].isspace() and not stripped.startswith("#"):
                break
            if stripped.startswith("url:"):
                base = stripped.split("url:", 1)[1].strip()
            elif "Authorization:" in stripped:
                value = stripped.split("Authorization:", 1)[1].strip().strip('"').strip("'")
                token = value.replace("Bearer ", "").replace("bearer ", "").strip()
    if base and token:
        return _normalize_base(base), token
    return None


def _resolve_creds() -> tuple[str, str] | None:
    return _creds_from_env() or _creds_from_file() or _creds_from_config()


def _clamp(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_TURN_CHARS:
        return text
    return text[: MAX_TURN_CHARS - 1] + "\u2026"


def _build_turns(extra: dict[str, Any]) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    user_message = extra.get("user_message")
    assistant_response = extra.get("assistant_response")
    if isinstance(user_message, str) and user_message.strip():
        turns.append({"role": "user", "content": _clamp(user_message)})
    if isinstance(assistant_response, str) and assistant_response.strip():
        turns.append({"role": "assistant", "content": _clamp(assistant_response)})
    return turns


def _post_turns(base: str, token: str, turns: list[dict[str, str]]) -> None:
    payload = json.dumps({"turns": turns}).encode("utf-8")
    request = urllib.request.Request(
        f"{base}/sessions/turns",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        extra = payload.get("extra")
        if not isinstance(extra, dict):
            extra = {}
        turns = _build_turns(extra)
        if turns:
            creds = _resolve_creds()
            if creds is not None:
                base, token = creds
                _post_turns(base, token, turns)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"[teamshared-capture] failed: {exc}", file=sys.stderr)
    except Exception as exc:  # never break the Hermes loop
        print(f"[teamshared-capture] unexpected error: {exc}", file=sys.stderr)
    sys.stdout.write("{}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
