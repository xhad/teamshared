"""Versioned REST API (``/v1``) for orgs, identities, memory, and admin.

Self-contained Starlette app mounted by the main HTTP server. Carries its own
principal auth, rate limiting, idempotency, error envelope, and pagination so
the multi-tenant surface is cleanly separated from the legacy MCP transport.
"""

from teamshared.server.api.app import build_api_app

__all__ = ["build_api_app"]
