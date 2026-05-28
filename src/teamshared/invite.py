"""One-time invite codes for self-service bearer token minting."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class InviteRecord:
    code: str
    agent: str | None
    uses_left: int
    created_at: str


class InviteStore:
    """JSON-file-backed invite registry."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        with self.path.open() as fh:
            raw = json.load(fh)
        invites = raw.get("invites", raw)
        if not isinstance(invites, dict):
            return {}
        return invites

    def _save(self, invites: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w") as fh:
            json.dump({"invites": invites}, fh, indent=2, sort_keys=True)
        tmp.replace(self.path)

    def create(self, *, agent: str | None = None, uses: int = 1) -> InviteRecord:
        if uses <= 0:
            raise ValueError("uses must be positive")
        code = secrets.token_urlsafe(12)
        record = {
            "agent": agent,
            "uses_left": uses,
            "created_at": datetime.now(UTC).isoformat(),
        }
        invites = self._load()
        invites[code] = record
        self._save(invites)
        return InviteRecord(
            code=code,
            agent=agent,
            uses_left=uses,
            created_at=record["created_at"],
        )

    def list_invites(self) -> list[InviteRecord]:
        out: list[InviteRecord] = []
        for code, entry in sorted(self._load().items()):
            uses_left = entry.get("uses_left", 0)
            if uses_left <= 0:
                continue
            out.append(
                InviteRecord(
                    code=code,
                    agent=entry.get("agent"),
                    uses_left=int(uses_left),
                    created_at=str(entry.get("created_at", "")),
                )
            )
        return out

    def get(self, code: str) -> InviteRecord | None:
        entry = self._load().get(code)
        if entry is None:
            return None
        uses_left = int(entry.get("uses_left", 0))
        if uses_left <= 0:
            return None
        return InviteRecord(
            code=code,
            agent=entry.get("agent"),
            uses_left=uses_left,
            created_at=str(entry.get("created_at", "")),
        )

    def redeem(self, code: str) -> InviteRecord | None:
        invites = self._load()
        entry = invites.get(code)
        if entry is None:
            return None
        uses_left = int(entry.get("uses_left", 0))
        if uses_left <= 0:
            return None
        entry["uses_left"] = uses_left - 1
        if entry["uses_left"] <= 0:
            del invites[code]
        else:
            invites[code] = entry
        self._save(invites)
        return InviteRecord(
            code=code,
            agent=entry.get("agent"),
            uses_left=max(int(entry.get("uses_left", 0)), 0),
            created_at=str(entry.get("created_at", "")),
        )
