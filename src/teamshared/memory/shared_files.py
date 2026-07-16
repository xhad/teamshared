"""Versioned HTML/Markdown shared files over :class:`TenantDb` (RLS-enforced).

Shared files are documents authored by agents (via MCP tools) or humans (via the
console). Each update creates a new immutable ``shared_file_versions`` row
(append-only history, same model as ``wiki_pages`` / ``skills``); the latest
version per file is the live content.

Shared files default to ``visibility='private'``. :meth:`publish` stamps a
``share_token`` UUID and flips visibility to ``'published'``; the public URL is
``/s/{share_token}``. The public read path (:meth:`get_published_by_token`,
:meth:`list_published_versions`, :meth:`get_published_version`) runs through
SECURITY DEFINER functions over an RLS-less ``db.admin()`` connection because
the public route has no org context -- the functions fail closed (return
nothing) unless the file is published AND active.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from teamshared.tenancy.context import TenantDb

_FILE_FIELDS = (
    "id", "org_id", "title", "content_format", "visibility", "share_token",
    "current_version", "status", "created_by", "created_at", "updated_at",
)
_FILE_SELECT = (
    "id, org_id, title, content_format, visibility, share_token, "
    "current_version, status, created_by, created_at, updated_at"
)


def _file_row(row: tuple[Any, ...]) -> dict[str, Any]:
    d = dict(zip(_FILE_FIELDS, row, strict=False))
    d["id"] = str(d["id"])
    d["org_id"] = str(d["org_id"])
    d["share_token"] = str(d["share_token"]) if d.get("share_token") else None
    return d


def _version_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "file_id": str(row[0]),
        "version": int(row[1]),
        "content": row[2],
        "content_format": row[3],
        "author_label": row[4],
        "created_at": row[5],
    }


class SharedFileStore:
    def __init__(self, db: TenantDb) -> None:
        self.db = db

    async def create(
        self,
        org_id: UUID,
        *,
        title: str,
        content: str,
        content_format: str = "markdown",
        author_label: str = "agent",
    ) -> dict[str, Any]:
        """Insert a new shared file + its first version row (version=1)."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"INSERT INTO shared_files "
                f"(org_id, title, content_format, current_version, created_by) "
                f"VALUES (%s,%s,%s,1,%s) RETURNING {_FILE_SELECT}",
                (str(org_id), title, content_format, author_label),
            )
            prow = await cur.fetchone()
            assert prow is not None
            file_id = prow[0]
            cur = await conn.execute(
                "INSERT INTO shared_file_versions "
                "(file_id, org_id, version, content, content_format, author_label) "
                "VALUES (%s,%s,1,%s,%s,%s) RETURNING "
                "file_id, version, content, content_format, author_label, created_at",
                (str(file_id), str(org_id), content, content_format, author_label),
            )
            vrow = await cur.fetchone()
        file = _file_row(prow)
        file["content"] = vrow[2]
        file["version"] = 1
        return file

    async def update(
        self,
        org_id: UUID,
        file_id: UUID,
        *,
        content: str,
        content_format: str | None = None,
        editor_label: str = "agent",
    ) -> dict[str, Any]:
        """Append a new version row (version = prior max + 1) and bump the file."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT current_version, content_format FROM shared_files WHERE id = %s",
                (str(file_id),),
            )
            prow = await cur.fetchone()
            if prow is None:
                return {}
            next_version = int(prow[0]) + 1
            fmt = content_format or prow[1]
            cur = await conn.execute(
                "INSERT INTO shared_file_versions "
                "(file_id, org_id, version, content, content_format, author_label) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING "
                "file_id, version, content, content_format, author_label, created_at",
                (str(file_id), str(org_id), next_version, content, fmt, editor_label),
            )
            vrow = await cur.fetchone()
            await conn.execute(
                "UPDATE shared_files SET current_version = %s, content_format = %s, "
                "updated_at = now() WHERE id = %s",
                (next_version, fmt, str(file_id)),
            )
            cur = await conn.execute(
                f"SELECT {_FILE_SELECT} FROM shared_files WHERE id = %s",
                (str(file_id),),
            )
            prow = await cur.fetchone()
        if prow is None:
            return {}
        file = _file_row(prow)
        file["content"] = vrow[2]
        file["version"] = next_version
        return file

    async def get(self, org_id: UUID, file_id: UUID) -> dict[str, Any] | None:
        """A shared file with its latest version content."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_FILE_SELECT} FROM shared_files WHERE id = %s AND status = 'active'",
                (str(file_id),),
            )
            prow = await cur.fetchone()
            if prow is None:
                return None
            cur = await conn.execute(
                "SELECT file_id, version, content, content_format, author_label, created_at "
                "FROM shared_file_versions WHERE file_id = %s AND version = %s",
                (str(file_id), prow[6]),
            )
            vrow = await cur.fetchone()
        file = _file_row(prow)
        if vrow is not None:
            file["content"] = vrow[2]
            file["content_format"] = vrow[3]
        return file

    async def get_version(
        self, org_id: UUID, file_id: UUID, version: int
    ) -> dict[str, Any] | None:
        """A specific version of a shared file."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_FILE_SELECT} FROM shared_files WHERE id = %s",
                (str(file_id),),
            )
            prow = await cur.fetchone()
            if prow is None:
                return None
            cur = await conn.execute(
                "SELECT file_id, version, content, content_format, author_label, created_at "
                "FROM shared_file_versions WHERE file_id = %s AND version = %s",
                (str(file_id), version),
            )
            vrow = await cur.fetchone()
        if vrow is None:
            return None
        file = _file_row(prow)
        file["content"] = vrow[2]
        file["content_format"] = vrow[3]
        file["version"] = vrow[1]
        return file

    async def list_plans(
        self, org_id: UUID, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        """All active shared files in the org, newest update first."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                f"SELECT {_FILE_SELECT} FROM shared_files WHERE status = 'active' "
                f"ORDER BY updated_at DESC LIMIT %s",
                (limit,),
            )
            rows = await cur.fetchall()
        return [_file_row(r) for r in rows]

    async def list_versions(
        self, org_id: UUID, file_id: UUID
    ) -> list[dict[str, Any]]:
        """All versions of a shared file, newest first."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT file_id, version, content, content_format, author_label, created_at "
                "FROM shared_file_versions WHERE file_id = %s ORDER BY version DESC",
                (str(file_id),),
            )
            rows = await cur.fetchall()
        return [_version_row(r) for r in rows]

    async def publish(
        self, org_id: UUID, file_id: UUID
    ) -> dict[str, Any]:
        """Flip visibility to published and stamp a share token (idempotent)."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT share_token FROM shared_files WHERE id = %s AND status = 'active'",
                (str(file_id),),
            )
            prow = await cur.fetchone()
            if prow is None:
                return {}
            existing_token = prow[0]
            if existing_token is not None:
                await conn.execute(
                    "UPDATE shared_files SET visibility = 'published', updated_at = now() "
                    "WHERE id = %s",
                    (str(file_id),),
                )
            else:
                await conn.execute(
                    "UPDATE shared_files SET visibility = 'published', "
                    "share_token = gen_random_uuid(), updated_at = now() WHERE id = %s",
                    (str(file_id),),
                )
            cur = await conn.execute(
                f"SELECT {_FILE_SELECT} FROM shared_files WHERE id = %s",
                (str(file_id),),
            )
            prow = await cur.fetchone()
        return _file_row(prow) if prow else {}

    async def unpublish(
        self, org_id: UUID, file_id: UUID
    ) -> dict[str, Any]:
        """Flip visibility back to private (share token retained for audit)."""
        async with self.db.org(org_id) as conn:
            await conn.execute(
                "UPDATE shared_files SET visibility = 'private', updated_at = now() WHERE id = %s",
                (str(file_id),),
            )
            cur = await conn.execute(
                f"SELECT {_FILE_SELECT} FROM shared_files WHERE id = %s",
                (str(file_id),),
            )
            prow = await cur.fetchone()
        return _file_row(prow) if prow else {}

    async def archive(self, org_id: UUID, file_id: UUID) -> bool:
        """Archive a shared file (versions retained for audit; excluded from active lists)."""
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "UPDATE shared_files SET status = 'archived', updated_at = now() "
                "WHERE id = %s AND status = 'active'",
                (str(file_id),),
            )
            changed = cur.rowcount > 0
        return changed

    # --- public read path (SECURITY DEFINER, no org context) -------------

    async def get_published_by_token(
        self, share_token: UUID | str
    ) -> dict[str, Any] | None:
        """Latest version of a published shared file, looked up by share token.

        Bypasses RLS via the ``public_shared_file_by_token`` SECURITY DEFINER
        function over an ``admin()`` connection (no org GUC). Fails closed:
        returns None unless the file is published AND active.
        """
        async with self.db.admin() as conn:
            cur = await conn.execute(
                "SELECT file_id, org_id, title, content_format, current_version, "
                "version, content, version_format, author_label, "
                "version_created, file_created, file_updated "
                "FROM public_shared_file_by_token(%s)",
                (str(share_token),),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "org_id": str(row[1]),
            "title": row[2],
            "content_format": row[3],
            "current_version": int(row[4]),
            "version": int(row[5]),
            "content": row[6],
            "version_format": row[7],
            "author_label": row[8],
            "version_created_at": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }

    async def get_published_version(
        self, share_token: UUID | str, version: int
    ) -> dict[str, Any] | None:
        """A specific published version, looked up by share token + version."""
        async with self.db.admin() as conn:
            cur = await conn.execute(
                "SELECT file_id, org_id, title, content_format, current_version, "
                "version, content, version_format, author_label, "
                "version_created, file_created, file_updated "
                "FROM public_shared_file_version_by_token(%s, %s)",
                (str(share_token), version),
            )
            row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": str(row[0]),
            "org_id": str(row[1]),
            "title": row[2],
            "content_format": row[3],
            "current_version": int(row[4]),
            "version": int(row[5]),
            "content": row[6],
            "version_format": row[7],
            "author_label": row[8],
            "version_created_at": row[9],
            "created_at": row[10],
            "updated_at": row[11],
        }

    async def list_published_versions(
        self, share_token: UUID | str
    ) -> list[dict[str, Any]]:
        """Version numbers + authors for the public version-history sidebar."""
        async with self.db.admin() as conn:
            cur = await conn.execute(
                "SELECT version, author_label, created_at "
                "FROM public_shared_file_versions_list(%s)",
                (str(share_token),),
            )
            rows = await cur.fetchall()
        return [
            {"version": int(r[0]), "author_label": r[1], "created_at": r[2]}
            for r in rows
        ]

    async def stats(self, org_id: UUID) -> dict[str, Any]:
        async with self.db.org(org_id) as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FILTER (WHERE status='active'), "
                "COUNT(*) FILTER (WHERE visibility='published'), "
                "COALESCE(SUM(current_version), 0) "
                "FROM shared_files WHERE status = 'active'"
            )
            row = await cur.fetchone()
        return {
            "files": int(row[0]) if row else 0,
            "published": int(row[1]) if row else 0,
            "versions": int(row[2]) if row else 0,
        }
