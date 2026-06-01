"""Tenant-scoped database access backed by Postgres Row-Level Security.

``TenantDb`` wraps a single :class:`AsyncConnectionPool` and hands out
connections in one of two modes:

* :meth:`TenantDb.org` -- opens a transaction, sets ``app.current_org_id`` for
  its lifetime via ``set_config(..., is_local => true)``, and yields the
  connection. Every statement run on it is constrained by the RLS policies, so
  cross-tenant reads/writes are impossible even if application SQL forgets a
  ``WHERE org_id = ...`` clause.
* :meth:`TenantDb.admin` -- opens a transaction with *no* org GUC. Use only for
  global, non-tenant tables (``permissions``) or the SECURITY DEFINER auth
  functions. On RLS tables this sees nothing (fails closed).

A ``current_org_id`` contextvar mirrors the active org for code that needs to
know the tenant without threading it through every call (e.g. audit).
"""

from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool

from teamshared.logging import get_logger

log = get_logger(__name__)

_current_org_id: contextvars.ContextVar[UUID | None] = contextvars.ContextVar(
    "teamshared_current_org_id", default=None
)


def current_org_id() -> UUID | None:
    """Return the org bound to the active tenant transaction, if any."""
    return _current_org_id.get()


def require_org_id() -> UUID:
    """Like :func:`current_org_id` but raises when no tenant is bound."""
    org = _current_org_id.get()
    if org is None:
        raise RuntimeError("No org context bound; wrap the call in TenantDb.org(...)")
    return org


class TenantDb:
    """RLS-aware connection provider."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 8) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: AsyncConnectionPool | None = None

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = AsyncConnectionPool(
            conninfo=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            open=False,
        )
        await self._pool.open()
        log.info("tenant_db_connected", dsn=self._dsn.split("@")[-1])

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> AsyncConnectionPool:
        if self._pool is None:
            raise RuntimeError("TenantDb not connected; call connect() first")
        return self._pool

    @asynccontextmanager
    async def org(self, org_id: UUID | str) -> AsyncIterator[AsyncConnection]:
        """Yield a connection inside a transaction scoped to ``org_id``.

        The org GUC is set ``is_local => true`` so it is automatically cleared
        when the transaction ends and never leaks to the next pool checkout.
        """
        org_uuid = org_id if isinstance(org_id, UUID) else UUID(str(org_id))
        async with self.pool.connection() as conn, conn.transaction():
            await conn.execute(
                "SELECT set_config('app.current_org_id', %s, true)",
                (str(org_uuid),),
            )
            token = _current_org_id.set(org_uuid)
            try:
                yield conn
            finally:
                _current_org_id.reset(token)

    @asynccontextmanager
    async def admin(self) -> AsyncIterator[AsyncConnection]:
        """Yield a connection with no org GUC (global tables / auth functions only)."""
        async with self.pool.connection() as conn, conn.transaction():
            yield conn
