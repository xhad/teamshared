"""One-time file-upload endpoint + local uploader script generator.

Flow:

1. An authenticated agent calls the ``file_upload_request`` MCP tool (or the
   console) which mints a single-use grant in Redis (see
   :meth:`WorkingMemory.set_file_upload_grant`) and returns an upload URL, a
   secret token, and a small self-deleting Python script.
2. The script runs on the user's machine, reads a local file, and POSTs the
   raw bytes to ``POST /v1/files/upload`` with ``X-Upload-Token``.
3. This handler pops the grant (single-use), sniffs the content format from the
   filename/Content-Type, creates the shared file via :class:`SharedFileStore`,
   optionally publishes it, and returns the file id + public URLs.

This lets large local HTML/Markdown files become shared files without pasting
their content through chat JSON (which breaks for big blobs).
"""

from __future__ import annotations

import os
import secrets
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse

from teamshared.logging import get_logger

log = get_logger(__name__)

# Hard cap on uploaded body size (5 MiB). Shared files are documents, not media.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

_GRANT_TTL_SECONDS = 600

_EXT_FORMAT = {".html": "html", ".htm": "html", ".md": "markdown", ".markdown": "markdown"}
_CTYPE_FORMAT = {
    "text/html": "html",
    "application/xhtml+xml": "html",
    "text/markdown": "markdown",
    "text/x-markdown": "markdown",
}


def sniff_content_format(filename: str | None, content_type: str | None, requested: str) -> str:
    """Resolve the file content_format: explicit request wins, else extension, else Content-Type, else markdown."""
    if requested and requested != "auto":
        return requested
    if filename:
        ext = os.path.splitext(filename)[1].lower()
        if ext in _EXT_FORMAT:
            return _EXT_FORMAT[ext]
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct in _CTYPE_FORMAT:
            return _CTYPE_FORMAT[ct]
    return "markdown"


def build_upload_script(
    *, upload_url: str, upload_token: str, filename: str | None, publish: bool,
    is_update: bool = False,
) -> str:
    """Return a self-contained Python (stdlib-only) uploader script body.

    The script reads a local file and POSTs it to ``upload_url`` with the
    one-time ``upload_token``, prints the server response, and deletes itself
    on success. ``is_update`` only changes the header comment (the server
    decides create-vs-update from the grant, not the script).
    """
    fname_repr = repr(filename) if filename else "None"
    publish_flag = "true" if publish else "false"
    purpose = "append a new version to an existing teamshared shared file" if is_update else "create a new teamshared shared file"
    return f"""#!/usr/bin/env python3
\"\"\"One-time teamshared file uploader (auto-generated). Self-deletes on success.

Purpose: {purpose}. Reads a local file, POSTs it to teamshared with the embedded
one-time token, prints the server response, and removes itself on success.
\"\"\"
import os, sys, urllib.request, urllib.error

UPLOAD_URL = {upload_url!r}
UPLOAD_TOKEN = {upload_token!r}
FILENAME = {fname_repr}
PUBLISH = {publish_flag}

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else FILENAME
    if not path:
        print("usage: python3 upload.py <path-to-file>", file=sys.stderr)
        return 2
    if not os.path.isfile(path):
        print("not a file:", path, file=sys.stderr)
        return 2
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) > {MAX_UPLOAD_BYTES}:
        print("file too large (max {MAX_UPLOAD_BYTES} bytes)", file=sys.stderr)
        return 1
    ext = os.path.splitext(path)[1].lower()
    if ext in (".html", ".htm"):
        ctype = "text/html; charset=utf-8"
    elif ext in (".md", ".markdown"):
        ctype = "text/markdown; charset=utf-8"
    else:
        ctype = "application/octet-stream"
    headers = {{
        "X-Upload-Token": UPLOAD_TOKEN,
        "X-Filename": os.path.basename(path),
        "X-Publish": "1" if PUBLISH else "0",
        "Content-Type": ctype,
    }}
    req = urllib.request.Request(UPLOAD_URL, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8", "replace")
            print(resp.status)
            print(body)
    except urllib.error.HTTPError as exc:
        print("upload failed:", exc.code, exc.read().decode("utf-8", "replace"), file=sys.stderr)
        return 1
    except Exception as exc:
        print("upload error:", exc, file=sys.stderr)
        return 1
    # Self-delete on success.
    try:
        os.remove(__file__)
    except OSError:
        pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
"""


async def mint_upload_grant(
    *,
    services: Any,
    org_id: UUID,
    principal_id: UUID,
    principal_type: str,
    principal_display: str,
    principal_attribution: str,
    title: str,
    content_format: str,
    filename: str | None,
    publish: bool,
    file_id: str | None = None,
    ttl: int = _GRANT_TTL_SECONDS,
) -> dict[str, Any]:
    """Mint a single-use upload grant and return the token + ttl.

    When ``file_id`` is provided the grant is in **update mode**: the uploaded
    body is appended as a new version to that existing shared file (instead of
    creating a new file). The grant stores ``file_id`` so the stateless upload
    handler knows which path to take.
    """
    token = secrets.token_urlsafe(32)
    payload = {
        "org_id": str(org_id),
        "principal_id": str(principal_id),
        "principal_type": principal_type,
        "principal_display": principal_display,
        "principal_attribution": principal_attribution,
        "title": title,
        "content_format": content_format,
        "filename": filename,
        "publish": bool(publish),
        "file_id": file_id,
        "mode": "update" if file_id else "create",
    }
    await services.working.set_file_upload_grant(token, payload, ttl=ttl)
    return {"token": token, "ttl": ttl}


async def handle_shared_file_upload(request: Request, services: Any) -> JSONResponse:
    """``POST /v1/files/upload`` — receive a file body and create a shared file.

    Authenticated by a single-use ``X-Upload-Token`` (minted via
    :func:`mint_upload_grant`). No bearer required; the route is in
    ``_PUBLIC`` so the inner PrincipalAuthMiddleware skips it.
    """
    token = (request.headers.get("x-upload-token") or "").strip()
    if not token:
        return JSONResponse({"error": {"code": "missing_token", "message": "X-Upload-Token required"}}, status_code=401)
    grant = await services.working.pop_file_upload_grant(token)
    if not grant:
        return JSONResponse({"error": {"code": "invalid_or_expired_token", "message": "upload token is invalid or expired"}}, status_code=401)

    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"error": {"code": "too_large", "message": f"upload exceeds {MAX_UPLOAD_BYTES} bytes"}},
            status_code=413,
        )
    try:
        content = body.decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse({"error": {"code": "bad_encoding", "message": "file must be UTF-8 text"}}, status_code=400)
    if not content.strip():
        return JSONResponse({"error": {"code": "empty", "message": "file is empty"}}, status_code=400)

    filename = request.headers.get("x-filename") or grant.get("filename")
    content_type = request.headers.get("content-type")
    requested_format = grant.get("content_format") or "auto"
    fmt = sniff_content_format(filename, content_type, requested_format)
    title = grant.get("title") or (os.path.splitext(filename or "")[0] or "Untitled file")

    try:
        org_id = UUID(grant["org_id"])
    except (KeyError, ValueError):
        return JSONResponse({"error": {"code": "bad_grant", "message": "grant is corrupt"}}, status_code=500)

    author_label = grant.get("principal_display") or grant.get("principal_attribution") or "agent"

    file_id_str = grant.get("file_id")
    if file_id_str:
        return await _handle_upload_update(services, grant, org_id, file_id_str, content, fmt, author_label)
    return await _handle_upload_create(services, grant, org_id, content, fmt, title, author_label)


async def _handle_upload_create(
    services: Any, grant: dict[str, Any], org_id: UUID, content: str, fmt: str,
    title: str, author_label: str,
) -> JSONResponse:
    try:
        file = await services.shared_files.create(
            org_id,
            title=title,
            content=content,
            content_format=fmt,
            author_label=author_label,
        )
    except Exception as exc:
        log.warning("file_upload_create_failed", error=str(exc))
        return JSONResponse({"error": {"code": "create_failed", "message": str(exc)}}, status_code=500)

    # Audit the create (attribution from the minting principal).
    try:
        await services.audit.record(
            agent=grant.get("principal_attribution") or author_label,
            action="file.create_via_upload",
            org_id=org_id,
            actor_type=grant.get("principal_type") or "agent",
            actor_id=grant.get("principal_id") or "00000000-0000-0000-0000-000000000000",
            resource_type="file",
            target_id=str(file.get("id")),
        )
    except Exception as exc:  # pragma: no cover - audit best-effort
        log.warning("file_upload_audit_failed", error=str(exc))

    out: dict[str, Any] = {
        "file_id": str(file.get("id")),
        "title": file.get("title"),
        "content_format": fmt,
        "version": file.get("version", 1),
    }

    # Optional auto-publish (mirrors facade.file_publish but without a live
    # Principal; the grant already authorized it at mint time).
    if grant.get("publish"):
        try:
            pub_row = await services.shared_files.publish(org_id, UUID(str(file["id"])))
            if pub_row:
                out["share_token"] = pub_row.get("share_token")
                out["slug"] = pub_row.get("slug")
                handle = pub_row.get("slug") or pub_row.get("share_token")
                out["public_url"] = f"/s/{handle}" if handle else None
                publisher = getattr(services, "file_publisher", None)
                if publisher and pub_row.get("share_token"):
                    latest = await services.shared_files.get(org_id, UUID(str(file["id"])))
                    if latest:
                        await _mirror_to_bucket(services, pub_row, latest)
                    direct = publisher.public_url(pub_row["share_token"])
                    if direct:
                        out["public_url_direct"] = direct
        except Exception as exc:
            log.warning("file_upload_publish_failed", error=str(exc))
            out["publish_error"] = str(exc)

    return JSONResponse(out, status_code=201)


async def _handle_upload_update(
    services: Any, grant: dict[str, Any], org_id: UUID, file_id_str: str,
    content: str, fmt: str, author_label: str,
) -> JSONResponse:
    """Append the uploaded body as a new version to an existing shared file."""
    try:
        file_id = UUID(file_id_str)
    except ValueError:
        return JSONResponse({"error": {"code": "bad_grant", "message": "grant file_id is corrupt"}}, status_code=500)

    # Verify the file exists + is active in this org (RLS-scoped read).
    existing = await services.shared_files.get(org_id, file_id)
    if not existing:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "file not found or not active"}},
            status_code=404,
        )

    try:
        file = await services.shared_files.update(
            org_id, file_id,
            content=content,
            content_format=fmt,
            editor_label=author_label,
        )
    except Exception as exc:
        log.warning("file_upload_update_failed", error=str(exc))
        return JSONResponse({"error": {"code": "update_failed", "message": str(exc)}}, status_code=500)

    try:
        await services.audit.record(
            agent=grant.get("principal_attribution") or author_label,
            action="file.update_via_upload",
            org_id=org_id,
            actor_type=grant.get("principal_type") or "agent",
            actor_id=grant.get("principal_id") or "00000000-0000-0000-0000-000000000000",
            resource_type="file",
            target_id=str(file.get("id")),
        )
    except Exception as exc:  # pragma: no cover - audit best-effort
        log.warning("file_upload_audit_failed", error=str(exc))

    out: dict[str, Any] = {
        "file_id": str(file.get("id")),
        "title": file.get("title"),
        "content_format": fmt,
        "version": file.get("version"),
        "updated": True,
    }

    # Honor an explicit publish request (idempotent if already published).
    if grant.get("publish"):
        try:
            await services.shared_files.publish(org_id, file_id)
        except Exception as exc:
            log.warning("file_upload_publish_failed", error=str(exc))

    # Re-mirror the bucket to the new current version when the file is published.
    fresh = await services.shared_files.get(org_id, file_id)
    if fresh and fresh.get("visibility") == "published" and fresh.get("share_token"):
        out["share_token"] = fresh.get("share_token")
        out["slug"] = fresh.get("slug")
        handle = fresh.get("slug") or fresh.get("share_token")
        out["public_url"] = f"/s/{handle}" if handle else None
        await _mirror_to_bucket(services, fresh, fresh)
        publisher = getattr(services, "file_publisher", None)
        if publisher:
            direct = publisher.public_url(fresh["share_token"])
            if direct:
                out["public_url_direct"] = direct

    return JSONResponse(out, status_code=200)


async def _mirror_to_bucket(services: Any, row: dict[str, Any], latest: dict[str, Any]) -> None:
    """Mirror raw HTML (or rendered markdown) to the bucket — mirrors facade behavior."""
    publisher = services.file_publisher
    token = row.get("share_token")
    version = row.get("version") or row.get("current_version")
    if not publisher or not token or not version:
        return
    content = latest.get("content") or ""
    fmt = latest.get("content_format") or "markdown"
    if fmt == "html":
        html = content  # raw, verbatim — interactive tools must work via CDN
    else:
        from teamshared.server.markdown_safe import render_markdown_safe
        html = render_markdown_safe(content)
    try:
        await publisher.publish_html(str(token), int(version), html)
    except Exception as exc:  # pragma: no cover - best-effort mirror
        log.warning("file_upload_bucket_failed", error=str(exc))
