"""Admin + user-controls service: members, roles, agents, retention, GDPR.

Thin, permission-checked operations over the tenant schema that back the admin
dashboard and user-facing memory controls. All reads/writes run in the org's
RLS context.
"""

from teamshared.admin.service import AdminService

__all__ = ["AdminService"]
