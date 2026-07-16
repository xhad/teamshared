"""REST handlers for the Gmail + Slack + Discord OAuth integration flow.

Two browser-driven routes (no bearer token — auth comes from the console
session cookie for ``start`` and from the signed Redis state nonce for
``callback``), plus an account-scoped listing route for programmatic access.

The start/callback routes are registered under ``/v1/integrations/oauth/*`` but
skip the ``/v1`` PrincipalAuthMiddleware (they are in the API app's
``public_paths``) because they authenticate via the console cookie / state
nonce rather than a bearer token.
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from teamshared.connectors import oauth as oauth_mod
from teamshared.connectors.registry import build_connector
from teamshared.identity.principal import Principal
from teamshared.identity.rbac import Permissions
from teamshared.identity.sessions import verify_session
from teamshared.logging import get_logger
from teamshared.memory.request_context import RequestContext
from teamshared.server.services import ProductionServices

log = get_logger(__name__)

_COOKIE = "ts_session"
_OAUTH_KINDS = ("gmail", "slack", "discord")
_SUPPORTED_KINDS = _OAUTH_KINDS


def _client_creds(services: ProductionServices, kind: str) -> tuple[str, str, str]:
    """Return (client_id, client_secret, redirect_uri) for ``kind``."""
    s = services.settings
    if kind == "gmail":
        if not s.gmail_client_id or not s.gmail_client_secret or not s.gmail_redirect_uri:
            raise RuntimeError("Gmail OAuth is not configured (set TEAMSHARED_GMAIL_*).")
        return s.gmail_client_id, s.gmail_client_secret, s.gmail_redirect_uri
    if kind == "slack":
        if not s.slack_client_id or not s.slack_client_secret or not s.slack_redirect_uri:
            raise RuntimeError("Slack OAuth is not configured (set TEAMSHARED_SLACK_*).")
        return s.slack_client_id, s.slack_client_secret, s.slack_redirect_uri
    if kind == "discord":
        if not s.discord_client_id or not s.discord_client_secret or not s.discord_redirect_uri:
            raise RuntimeError("Discord OAuth is not configured (set TEAMSHARED_DISCORD_*).")
        return s.discord_client_id, s.discord_client_secret, s.discord_redirect_uri
    raise ValueError(f"unsupported integration kind: {kind!r}")


def _session_principal(request: Request, services: ProductionServices) -> Principal | None:
    secret = services.settings.session_secret
    if not secret:
        return None
    token = request.cookies.get(_COOKIE)
    if not token:
        return None
    return verify_session(token, secret=secret)


def _ctx(principal: Principal, services: ProductionServices) -> RequestContext:
    return RequestContext(
        principal=principal, db=services.tenant_db, authorizer=services.authorizer()
    )


def integration_routes(services: ProductionServices) -> list[Route]:
    """Build the OAuth + integration REST routes bound to ``services``."""

    async def oauth_start(request: Request) -> Response:
        kind = (request.query_params.get("kind") or "").strip().lower()
        if kind not in _SUPPORTED_KINDS:
            return JSONResponse(
                {"error": {"code": "bad_request", "message": f"kind must be one of {_SUPPORTED_KINDS}"}},
                status_code=400,
            )
        principal = _session_principal(request, services)
        if principal is None:
            return RedirectResponse("/login", status_code=303)
        try:
            client_id, _secret, redirect_uri = _client_creds(services, kind)
        except (RuntimeError, ValueError) as exc:
            return JSONResponse(
                {"error": {"code": "not_configured", "message": str(exc)}},
                status_code=503,
            )
        state = secrets.token_urlsafe(24)
        await services.working.set_oauth_state(
            state,
            {
                "account_id": str(principal.account_id) if principal.account_id else None,
                "org_id": str(principal.org_id),
                "kind": kind,
                "redirect_uri": redirect_uri,
            },
        )
        authorize_url = oauth_mod.build_authorize_url(
            kind, client_id=client_id, redirect_uri=redirect_uri, state=state,
        )
        # Console (browser) requests get a redirect; programmatic callers
        # (Accept: application/json) get the URL as JSON so they can open it.
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse({"authorize_url": authorize_url, "kind": kind})
        return RedirectResponse(authorize_url, status_code=302)

    async def oauth_callback(request: Request) -> Response:
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return RedirectResponse("/app/connections?status=error&reason=missing_params", status_code=303)
        payload = await services.working.pop_oauth_state(state)
        if payload is None:
            return RedirectResponse("/app/connections?status=error&reason=invalid_state", status_code=303)
        kind = payload.get("kind")
        if kind not in _SUPPORTED_KINDS:
            return RedirectResponse("/app/connections?status=error&reason=bad_kind", status_code=303)
        try:
            client_id, client_secret, redirect_uri = _client_creds(services, kind)
            result = await oauth_mod.exchange_code(
                kind, code=code, client_id=client_id,
                client_secret=client_secret, redirect_uri=redirect_uri,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("oauth_exchange_failed", kind=kind, error=str(exc))
            return RedirectResponse(f"/app/connections?status=error&reason=exchange_failed&kind={kind}", status_code=303)

        # Recover the principal from the console cookie so we have a real
        # RequestContext (RBAC + RLS). The state nonce carried the org/account,
        # but the cookie is the trusted identity.
        principal = _session_principal(request, services)
        if principal is None:
            return RedirectResponse("/app/connections?status=error&reason=no_session", status_code=303)

        ctx = _ctx(principal, services)
        name = result.display_name or f"{kind}-{(principal.display or 'me').split('@')[0]}"
        config: dict[str, Any] = dict(result.config or {})
        try:
            build_connector(kind, config)
        except ValueError:
            config = {}
        try:
            await services.connectors.create_oauth_connection(
                ctx, kind=kind, name=name, config=config, bundle=result.bundle,
            )
        except Exception as exc:  # noqa: BLE001
            log.error("oauth_connection_store_failed", kind=kind, error=str(exc))
            return RedirectResponse(f"/app/connections?status=error&reason=store_failed&kind={kind}", status_code=303)
        log.info("oauth_connected", kind=kind, org_id=str(principal.org_id), account_id=str(principal.account_id))
        return RedirectResponse(f"/app/connections?status=connected&kind={kind}", status_code=303)

    async def list_integrations(request: Request) -> JSONResponse:
        ctx = _ctx(request.state.principal, services)
        items = await services.connectors.list_connectors(ctx)
        # Surface account-scoped (OAuth) connections distinctly.
        return JSONResponse({"integrations": items})

    async def disconnect_integration(request: Request) -> JSONResponse:
        ctx = _ctx(request.state.principal, services)
        connector_id = UUID(request.path_params["connector_id"])
        # Best-effort revoke at the provider before deleting the row.
        try:
            conn = await services.connectors.get_connector(ctx, connector_id)
            if conn is not None and conn.get("kind") in _OAUTH_KINDS:
                bundle = await services.connectors.get_token_bundle(ctx, connector_id)
                if bundle is not None:
                    await oauth_mod.revoke_token(conn["kind"], token=bundle.access_token)
        except Exception:  # noqa: BLE001
            pass
        ok = await services.connectors.delete(ctx, connector_id)
        return JSONResponse({"deleted": ok})

    async def sync_integration(request: Request) -> JSONResponse:
        ctx = _ctx(request.state.principal, services)
        await ctx.authorizer.require(ctx.principal, Permissions.CONNECTOR_MANAGE)
        report = await services.connectors.sync(ctx, UUID(request.path_params["connector_id"]))
        return JSONResponse(
            {"connector_id": str(report.connector_id), "fetched": report.fetched,
             "imported": report.imported, "next_cursor": report.next_cursor}
        )

    return [
        Route("/integrations/oauth/start", oauth_start, methods=["GET"]),
        Route("/integrations/oauth/callback", oauth_callback, methods=["GET"]),
        Route("/integrations", list_integrations, methods=["GET"]),
        Route("/integrations/{connector_id}", disconnect_integration, methods=["DELETE"]),
        Route("/integrations/{connector_id}/sync", sync_integration, methods=["POST"]),
    ]
