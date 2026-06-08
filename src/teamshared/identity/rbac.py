"""Role-based access control: resolve and enforce a principal's permissions.

Effective permissions are the union of permissions granted by the principal's
role bindings, optionally intersected with the presenting API key's declared
scopes (least privilege). The :class:`Authorizer` caches per-principal results
for the lifetime of one :class:`Authorizer` instance. Build a fresh instance per
inbound request (``ProductionServices.authorizer()``) and pass it on
:class:`~teamshared.memory.request_context.RequestContext`; do not store
:class:`~teamshared.memory.service.MemoryService` or long-lived pipelines with
a process-wide authorizer.
"""

from __future__ import annotations

from teamshared.identity.principal import Principal
from teamshared.metrics import METRICS
from teamshared.tenancy.context import TenantDb


class Permissions:
    """Canonical permission codes (mirror of the ``permissions`` catalog)."""

    MEMORY_CREATE = "memory:create"
    MEMORY_READ = "memory:read"
    MEMORY_UPDATE = "memory:update"
    MEMORY_DELETE = "memory:delete"
    MEMORY_APPROVE = "memory:approve"
    MEMORY_SHARE = "memory:share"
    MEMORY_EXPORT = "memory:export"
    MEMORY_ADMIN = "memory:admin"
    CONNECTOR_MANAGE = "connector:manage"
    AUDIT_READ = "audit:read"
    BILLING_MANAGE = "billing:manage"
    ORG_ADMIN = "org:admin"
    WORK_READ = "work:read"
    WORK_WRITE = "work:write"


class PermissionDenied(Exception):  # noqa: N818 - idiomatic name; not an *Error
    """Raised when a principal lacks a required permission."""

    def __init__(self, permission: str, principal: Principal) -> None:
        self.permission = permission
        self.principal = principal
        super().__init__(
            f"principal {principal.type}:{principal.id} lacks permission {permission!r}"
        )


def implies_permission(granted: frozenset[str], permission: str) -> bool:
    """Return whether ``granted`` satisfies ``permission``, including implied caps."""
    if permission in granted:
        return True
    if Permissions.MEMORY_ADMIN in granted and permission.startswith("memory:"):
        return True
    if Permissions.ORG_ADMIN in granted and permission.startswith("work:"):
        return True
    if permission == Permissions.WORK_READ and Permissions.MEMORY_READ in granted:
        return True
    return permission == Permissions.WORK_WRITE and Permissions.MEMORY_CREATE in granted


class Authorizer:
    def __init__(self, db: TenantDb) -> None:
        self.db = db
        self._cache: dict[tuple[str, str], frozenset[str]] = {}

    async def effective_permissions(self, principal: Principal) -> frozenset[str]:
        cache_key = (str(principal.org_id), f"{principal.type}:{principal.id}")
        if cache_key in self._cache:
            granted = self._cache[cache_key]
        else:
            async with self.db.org(principal.org_id) as conn:
                cur = await conn.execute(
                    """
                    SELECT DISTINCT rp.permission_code
                    FROM role_bindings rb
                    JOIN role_permissions rp ON rp.role_id = rb.role_id
                    WHERE rb.principal_type = %s AND rb.principal_id = %s
                    """,
                    (principal.type, str(principal.id)),
                )
                rows = await cur.fetchall()
            granted = frozenset(r[0] for r in rows)
            self._cache[cache_key] = granted

        if principal.scopes:
            # The presenting key narrows -- never widens -- the actor's perms.
            return granted & frozenset(principal.scopes)
        return granted

    async def has(self, principal: Principal, permission: str) -> bool:
        perms = await self.effective_permissions(principal)
        return implies_permission(perms, permission)

    async def require(self, principal: Principal, permission: str) -> None:
        if not await self.has(principal, permission):
            METRICS.permission_denied.inc(permission=permission)
            raise PermissionDenied(permission, principal)
