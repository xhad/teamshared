"""Multi-tenant primitives: org context + RLS-scoped database access.

The central guarantee lives in :class:`~teamshared.tenancy.context.TenantDb`:
every tenant query runs inside a transaction that has set the
``app.current_org_id`` GUC, which the Postgres RLS policies (migration 006)
key on. Forget to set it and the policy matches zero rows -- a missing tenant
context fails closed.
"""

from teamshared.tenancy.context import (
    TenantDb,
    current_org_id,
    require_org_id,
)
from teamshared.tenancy.models import Membership, Organization, Project, Team

__all__ = [
    "Membership",
    "Organization",
    "Project",
    "Team",
    "TenantDb",
    "current_org_id",
    "require_org_id",
]
