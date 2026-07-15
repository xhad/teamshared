"""Concrete connector adapters.

Each adapter speaks its source's real API shape via httpx. They require a valid
decrypted OAuth/PAT token (provided by the vault) to fetch live data; the
framework and importer are exercised in tests with a FakeConnector. Adapters
deliberately keep parsing small -- they map a source object to a ``SourceDoc``
with an ``acl`` that mirrors the source's visibility.
"""

from __future__ import annotations

import base64
import email.utils
from email.message import EmailMessage
from typing import Any, cast

import httpx

from teamshared.connectors.base import Connector, SourceDoc, SyncResult


def _headers_map(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("payload", {}).get("headers") or payload.get("headers") or []
    return {h["name"].lower(): h["value"] for h in headers}


def _gmail_body(payload: dict[str, Any]) -> str:
    """Extract a best-effort text/plain body from a Gmail message payload."""
    parts = payload.get("payload", {}).get("parts") or []
    if not parts and payload.get("payload", {}).get("body", {}).get("data"):
        return _b64url_decode(payload["payload"]["body"]["data"])
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return _b64url_decode(part["body"]["data"])
    for part in parts:
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            return _b64url_decode(part["body"]["data"])
    return ""


def _b64url_decode(data: str) -> str:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad).decode("utf-8", errors="replace")


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

    async def post_message(
        self, token: str, channel: str, text: str, *, thread_ts: str | None = None
    ) -> dict[str, Any]:
        """Post a message to a Slack channel (optionally as a thread reply)."""
        body: dict[str, Any] = {"channel": channel, "text": text}
        if thread_ts:
            body["thread_ts"] = thread_ts
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage", json=body, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack chat.postMessage failed: {data.get('error')}")
        return cast(dict[str, Any], data)

    async def list_thread_replies(
        self, token: str, channel: str, ts: str
    ) -> list[dict[str, Any]]:
        """Return the messages in a Slack thread (parent + replies)."""
        headers = {"Authorization": f"Bearer {token}"}
        params: dict[str, str | int] = {"channel": channel, "ts": ts, "limit": 200}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "https://slack.com/api/conversations.replies", params=params, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"slack conversations.replies failed: {data.get('error')}")
        return cast(list[dict[str, Any]], data.get("messages", []))


class GmailConnector(Connector):
    """Gmail integration: read messages (sync + search) and send email.

    Sync is incremental via the ``historyId`` cursor: each fetch lists recent
    INBOX messages and records the latest ``historyId`` so the next pass can
    use ``users.me.history.list`` for a delta. For v1 we re-list and rely on
    ingestion dedup (checksum) to avoid double-imports.
    """

    kind = "gmail"
    _base = "https://gmail.googleapis.com/gmail/v1"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        headers = {"Authorization": f"Bearer {token}"}
        params: dict[str, Any] = {"maxResults": 50, "labelIds": "INBOX"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base}/users/me/messages", params=params, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        msg_refs = data.get("messages", [])
        docs: list[SourceDoc] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for ref in msg_refs:
                mid = ref.get("id")
                if not mid:
                    continue
                r = await client.get(
                    f"{self._base}/users/me/messages/{mid}?format=full", headers=headers
                )
                if r.status_code != 200:
                    continue
                msg = r.json()
                docs.append(self._msg_to_doc(msg))
        history_id = data.get("historyId")
        return SyncResult(documents=docs, next_cursor=history_id, has_more=False)

    async def list_messages(
        self, token: str, query: str, *, max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Search Gmail messages; return lightweight hit metadata (id, snippet, threadId)."""
        headers = {"Authorization": f"Bearer {token}"}
        params: dict[str, str | int] = {"q": query, "maxResults": max_results}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base}/users/me/messages", params=params, headers=headers
            )
            resp.raise_for_status()
            data = resp.json()
        out: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for ref in data.get("messages", []):
                mid = ref.get("id")
                r = await client.get(
                    f"{self._base}/users/me/messages/{mid}?format=metadata", headers=headers
                )
                if r.status_code != 200:
                    continue
                msg = r.json()
                hm = _headers_map(msg)
                out.append({
                    "id": mid,
                    "thread_id": msg.get("threadId"),
                    "snippet": msg.get("snippet", ""),
                    "from": hm.get("from", ""),
                    "subject": hm.get("subject", ""),
                    "date": hm.get("date", ""),
                })
        return out

    async def get_message(self, token: str, message_id: str) -> dict[str, Any]:
        """Fetch one full message (headers + body)."""
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self._base}/users/me/messages/{message_id}?format=full", headers=headers
            )
            resp.raise_for_status()
            msg = resp.json()
        hm = _headers_map(msg)
        return {
            "id": msg.get("id"),
            "thread_id": msg.get("threadId"),
            "from": hm.get("from", ""),
            "to": hm.get("to", ""),
            "subject": hm.get("subject", ""),
            "date": hm.get("date", ""),
            "body": _gmail_body(msg),
            "snippet": msg.get("snippet", ""),
        }

    async def send(
        self, token: str, *, to: str, subject: str, body: str, thread_id: str | None = None
    ) -> dict[str, Any]:
        """Send an email (optionally as a reply in a thread)."""
        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        if thread_id:
            # Reply: set threadId so Gmail threads it. In-Reply-To/References
            # require the original Message-ID, which we fetch here.
            original = await self.get_message(token, thread_id)
            orig_id = original.get("id")
            if orig_id:
                msg["In-Reply-To"] = f"<{orig_id}>"
                msg["References"] = f"<{orig_id}>"
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
        payload: dict[str, Any] = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self._base}/users/me/messages/send", json=payload, headers=headers
            )
            resp.raise_for_status()
            return cast(dict[str, Any], resp.json())

    def _msg_to_doc(self, msg: dict[str, Any]) -> SourceDoc:
        hm = _headers_map(msg)
        mid = msg.get("id", "")
        subject = hm.get("subject", "")
        sender = hm.get("from", "")
        body = _gmail_body(msg)
        content = f"From: {sender}\nSubject: {subject}\n\n{body}".strip()
        return SourceDoc(
            external_id=f"gmail:{mid}",
            title=subject or None,
            content=content,
            uri=f"https://mail.google.com/mail/u/0/#inbox/{mid}",
            acl={"from": sender, "to": hm.get("to", ""), "thread_id": msg.get("threadId")},
            metadata={
                "message_id": mid,
                "thread_id": msg.get("threadId"),
                "date": hm.get("date"),
                "from": sender,
                "subject": subject,
            },
        )


class TelegramConnector(Connector):
    """Telegram Bot API integration: read messages (getUpdates) and send.

    Telegram bots authenticate with a static bot token (from @BotFather) — no
    OAuth, no refresh, no expiry. The token is stored as a ``TokenBundle`` with
    only ``access_token`` set. Sync polls ``getUpdates`` with an offset cursor
    (the last ``update_id`` + 1) so each pass fetches only new messages.
    """

    kind = "telegram"
    _base = "https://api.telegram.org"

    async def fetch(self, token: str, cursor: str | None) -> SyncResult:
        params: dict[str, str | int] = {"timeout": 0, "limit": 100}
        if cursor:
            params["offset"] = int(cursor)
        async with httpx.AsyncClient(timeout=35.0) as client:
            resp = await client.get(
                f"{self._base}/bot{token}/getUpdates", params=params
            )
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram getUpdates failed: {data.get('description')}")
        updates = data.get("result", [])
        docs: list[SourceDoc] = []
        next_offset: str | None = None
        for u in updates:
            msg = u.get("message") or u.get("edited_message")
            if not msg:
                continue
            chat = msg.get("chat", {})
            chat_id = chat.get("id")
            text = msg.get("text", "")
            sender = (msg.get("from") or {}).get("username") or (msg.get("from") or {}).get("first_name", "")
            content = f"From: {sender}\nChat: {chat.get('title') or chat.get('username') or chat_id}\n\n{text}".strip()
            docs.append(
                SourceDoc(
                    external_id=f"telegram:{u.get('update_id')}",
                    title=chat.get("title") or f"Telegram {chat_id}",
                    content=content,
                    uri=f"https://web.telegram.org/#/im?p=c{chat_id}" if chat_id else None,
                    acl={"chat_id": chat_id, "chat_type": chat.get("type")},
                    metadata={
                        "update_id": u.get("update_id"),
                        "message_id": msg.get("message_id"),
                        "chat_id": chat_id,
                        "from": sender,
                        "date": msg.get("date"),
                    },
                )
            )
            next_offset = str(int(u["update_id"]) + 1)
        return SyncResult(documents=docs, next_cursor=next_offset, has_more=False)

    async def list_messages(
        self, token: str, query: str, *, max_results: int = 10
    ) -> list[dict[str, Any]]:
        """Search recent updates client-side (Telegram has no search API for bots)."""
        result = await self.fetch(token, None)
        ql = query.lower()
        out: list[dict[str, Any]] = []
        for d in result.documents:
            if ql in d.content.lower():
                out.append({
                    "id": d.external_id,
                    "chat_id": d.acl.get("chat_id"),
                    "text": d.content,
                    "from": d.metadata.get("from", ""),
                })
                if len(out) >= max_results:
                    break
        return out

    async def get_message(self, token: str, message_id: str) -> dict[str, Any]:
        """Fetch one message by 'chat_id:message_id' via getChat + recent history.

        Telegram bots cannot fetch an arbitrary message by id alone; this is a
        best-effort lookup that scans the latest update batch for the id.
        """
        result = await self.fetch(token, None)
        target = message_id.split(":")[-1] if ":" in message_id else message_id
        for d in result.documents:
            if str(d.metadata.get("message_id")) == target:
                return {
                    "id": d.external_id,
                    "chat_id": d.acl.get("chat_id"),
                    "from": d.metadata.get("from", ""),
                    "text": d.content,
                    "date": d.metadata.get("date"),
                }
        return {"id": message_id, "text": "", "not_found": True}

    async def send(
        self, token: str, *, to: str, subject: str, body: str, thread_id: str | None = None
    ) -> dict[str, Any]:
        """Send a message to a Telegram chat (``to`` = chat_id).

        ``subject`` is ignored (Telegram has no subject line); ``thread_id`` maps to
        ``message_thread_id`` for forum-topic replies.
        """
        return await self.post_message(token, to, body, thread_ts=thread_id)

    async def post_message(
        self, token: str, channel: str, text: str, *, thread_ts: str | None = None
    ) -> dict[str, Any]:
        """Post a message to a Telegram chat (``channel`` = chat_id)."""
        payload: dict[str, Any] = {"chat_id": channel, "text": text}
        if thread_ts:
            payload["message_thread_id"] = int(thread_ts)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{self._base}/bot{token}/sendMessage", json=payload)
            resp.raise_for_status()
            data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"telegram sendMessage failed: {data.get('description')}")
        return cast(dict[str, Any], data.get("result", data))

    async def list_thread_replies(
        self, token: str, channel: str, thread_ts: str
    ) -> list[dict[str, Any]]:
        """Telegram threads are forum topics; bots see replies via getUpdates."""
        result = await self.fetch(token, None)
        out: list[dict[str, Any]] = []
        for d in result.documents:
            if d.acl.get("chat_id") == _to_int(channel) and d.metadata.get("message_id") != _to_int(thread_ts):
                out.append({
                    "message_id": d.metadata.get("message_id"),
                    "from": d.metadata.get("from", ""),
                    "text": d.content,
                })
        return out


def _to_int(val: Any) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


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
