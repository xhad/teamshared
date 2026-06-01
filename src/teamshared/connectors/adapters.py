"""Concrete connector adapters.

Each adapter speaks its source's real API shape via httpx. They require a valid
decrypted OAuth/PAT token (provided by the vault) to fetch live data; the
framework and importer are exercised in tests with a FakeConnector. Adapters
deliberately keep parsing small -- they map a source object to a ``SourceDoc``
with an ``acl`` that mirrors the source's visibility.
"""

from __future__ import annotations

from typing import Any

import httpx

from teamshared.connectors.base import Connector, SourceDoc, SyncResult


class GitHubConnector(Connector):
    kind = "github"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        repo = self.config["repo"]  # "owner/name"
        params: dict[str, Any] = {"state": "all", "per_page": 50}
        if cursor:
            params["since"] = cursor
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/issues", params=params, headers=headers
            )
            resp.raise_for_status()
            issues = resp.json()
        docs = [
            SourceDoc(
                external_id=f"issue:{i['number']}",
                title=i.get("title"),
                content=f"{i.get('title', '')}\n\n{i.get('body') or ''}",
                uri=i.get("html_url"),
                acl={"repo": repo, "visibility": "private"},
                metadata={"updated_at": i.get("updated_at"), "state": i.get("state")},
            )
            for i in issues
            if "pull_request" not in i
        ]
        next_cursor = issues[-1].get("updated_at") if issues else cursor
        return SyncResult(documents=docs, next_cursor=next_cursor, has_more=len(issues) == 50)


class SlackConnector(Connector):
    kind = "slack"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        channel = self.config["channel"]
        params: dict[str, Any] = {"channel": channel, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://slack.com/api/conversations.history", params=params, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        msgs = data.get("messages", [])
        docs = [
            SourceDoc(
                external_id=f"{channel}:{m.get('ts')}",
                content=m.get("text", ""),
                acl={"channel": channel},
                metadata={"ts": m.get("ts"), "user": m.get("user")},
            )
            for m in msgs
            if m.get("text")
        ]
        next_cursor = data.get("response_metadata", {}).get("next_cursor") or None
        return SyncResult(documents=docs, next_cursor=next_cursor, has_more=bool(next_cursor))


class NotionConnector(Connector):
    kind = "notion"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {"page_size": 50, "filter": {"property": "object", "value": "page"}}
        if cursor:
            body["start_cursor"] = cursor
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.notion.com/v1/search", json=body, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        docs = [
            SourceDoc(
                external_id=p["id"],
                content=_notion_title(p),
                uri=p.get("url"),
                acl={"workspace": self.config.get("workspace")},
                metadata={"last_edited": p.get("last_edited_time")},
            )
            for p in data.get("results", [])
        ]
        return SyncResult(
            documents=docs, next_cursor=data.get("next_cursor"), has_more=data.get("has_more", False)
        )


class GoogleDriveConnector(Connector):
    kind = "gdrive"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        params: dict[str, Any] = {
            "pageSize": 50,
            "fields": "nextPageToken, files(id, name, mimeType, modifiedTime, webViewLink)",
        }
        if cursor:
            params["pageToken"] = cursor
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://www.googleapis.com/drive/v3/files", params=params, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        docs = [
            SourceDoc(
                external_id=f["id"],
                title=f.get("name"),
                content=f.get("name", ""),
                uri=f.get("webViewLink"),
                acl={"drive": self.config.get("drive_id", "my-drive")},
                metadata={"mimeType": f.get("mimeType"), "modifiedTime": f.get("modifiedTime")},
            )
            for f in data.get("files", [])
        ]
        return SyncResult(
            documents=docs, next_cursor=data.get("nextPageToken"), has_more=bool(data.get("nextPageToken"))
        )


class LinearConnector(Connector):
    kind = "linear"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        after = f', after: "{cursor}"' if cursor else ""
        query = (
            f"{{ issues(first: 50{after}) {{ pageInfo {{ hasNextPage endCursor }} "
            "nodes { id identifier title description updatedAt team { key } } } }"
        )
        headers = {"Authorization": token, "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.linear.app/graphql", json={"query": query}, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()["data"]["issues"]
        docs = [
            SourceDoc(
                external_id=n["id"],
                title=n.get("title"),
                content=f"{n.get('identifier', '')} {n.get('title', '')}\n\n{n.get('description') or ''}",
                acl={"team": (n.get("team") or {}).get("key")},
                metadata={"updatedAt": n.get("updatedAt")},
            )
            for n in data["nodes"]
        ]
        page = data["pageInfo"]
        return SyncResult(
            documents=docs,
            next_cursor=page.get("endCursor"),
            has_more=page.get("hasNextPage", False),
        )


class MCPConnector(Connector):
    kind = "mcp"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        """Pull resource listings from a remote MCP server as documents."""
        base = self.config["url"].rstrip("/")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/resources/list", json={}, headers=headers
            )
            resp.raise_for_status()
            resources = resp.json().get("resources", [])
        docs = [
            SourceDoc(
                external_id=r.get("uri", r.get("name", "")),
                title=r.get("name"),
                content=r.get("description", "") or r.get("name", ""),
                uri=r.get("uri"),
                acl={"server": base},
            )
            for r in resources
        ]
        return SyncResult(documents=docs, next_cursor=None, has_more=False)


def _notion_title(page: dict[str, Any]) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    return str(page.get("id", ""))
