"""``/admin`` dashboard routes: magic-link login + read-only admin pages (K1).

Login is an owner-email magic link backed by ``session_secret``:

1. ``POST /admin/login`` {email} -> look up the user in the default org, mint a
   short-lived ``typ=magic`` JWT. In dev (``auth_disabled``) the link is shown;
   in prod it is logged + a masked confirmation is shown (no mailer yet).
2. ``GET /admin/login/verify?token=`` -> ``verify_magic`` -> ``issue_session``
   -> set an HttpOnly ``ts_session`` cookie -> redirect to ``/admin``.
3. ``/admin/*`` pages are gated by that cookie (``verify_session`` -> Principal);
   missing/invalid cookie redirects to the login page.

Pages are read-only views over :class:`AdminService` + ``ProductionServices``.
``PermissionDenied`` renders a 403 page; other backend errors degrade to an
"unavailable" note rather than a 500.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from teamshared.config import Settings
from teamshared.identity.principal import Principal
from teamshared.identity.rbac import PermissionDenied, Permissions
from teamshared.identity.sessions import issue_magic, issue_session, verify_magic, verify_session
from teamshared.logging import get_logger
from teamshared.memory.request_context import RequestContext
from teamshared.server import admin_ui
from teamshared.server.services import ProductionServices

log = get_logger(__name__)

_COOKIE = "ts_session"
_SESSION_TTL = 3600


def register_admin_routes(settings: Settings, services: ProductionServices) -> list[Route]:
    """Build the ``/admin`` route table bound to ``settings`` + ``services``."""

    def _ctx(principal: Principal) -> RequestContext:
        return RequestContext(
            principal=principal, db=services.tenant_db, authorizer=services.authorizer()
        )

    def _session(request: Request) -> Principal | None:
        if not settings.session_secret:
            return None
        token = request.cookies.get(_COOKIE)
        if not token:
            return None
        return verify_session(token, secret=settings.session_secret)

    def _redirect_login() -> RedirectResponse:
        return RedirectResponse("/admin/login", status_code=303)

    async def _resolve_owner_user_id(email: str) -> UUID | None:
        async with services.tenant_db.org(settings.default_org_id) as conn:
            cur = await conn.execute(
                "SELECT id FROM users WHERE email = %s AND status = 'active'", (email,)
            )
            row = await cur.fetchone()
        return row[0] if row else None

    # --- auth flow -------------------------------------------------------

    async def login_get(request: Request) -> HTMLResponse:
        if not settings.session_secret:
            return HTMLResponse(
                admin_ui.login_page(
                    message="Dashboard login is disabled: set TEAMSHARED_SESSION_SECRET.",
                    error=True,
                ),
                status_code=503,
            )
        return HTMLResponse(admin_ui.login_page())

    async def login_post(request: Request) -> Response:
        if not settings.session_secret:
            return HTMLResponse(
                admin_ui.login_page(message="Login disabled (no session secret).", error=True),
                status_code=503,
            )
        form = await request.form()
        email = str(form.get("email") or "").strip().lower()
        if not email:
            return HTMLResponse(admin_ui.login_page(message="Email is required.", error=True))
        user_id = await _resolve_owner_user_id(email)
        # Always render the same confirmation to avoid leaking which emails exist.
        if user_id is None:
            log.info("admin_login_unknown_email", email=email)
            return HTMLResponse(
                admin_ui.login_page(message="If that account exists, a sign-in link was sent.")
            )
        token = issue_magic(
            secret=settings.session_secret,
            org_id=settings.default_org_id,
            user_id=user_id,
        )
        base = (settings.public_url or "").rstrip("/")
        link = f"{base}/admin/login/verify?token={token}"
        if settings.auth_disabled:
            return HTMLResponse(admin_ui.login_page(message="Dev mode:", magic_link=link))
        log.info("admin_magic_link_issued", email=email, link=link)
        return HTMLResponse(
            admin_ui.login_page(message="If that account exists, a sign-in link was sent.")
        )

    async def login_verify(request: Request) -> Response:
        if not settings.session_secret:
            return _redirect_login()
        token = request.query_params.get("token", "")
        principal = verify_magic(token, secret=settings.session_secret)
        if principal is None:
            return HTMLResponse(
                admin_ui.login_page(message="That link is invalid or expired.", error=True),
                status_code=401,
            )
        session = issue_session(
            secret=settings.session_secret,
            org_id=principal.org_id,
            user_id=principal.id,
            ttl_seconds=_SESSION_TTL,
        )
        resp = RedirectResponse("/admin", status_code=303)
        resp.set_cookie(
            _COOKIE, session, max_age=_SESSION_TTL, httponly=True, samesite="lax",
            secure=not settings.auth_disabled, path="/admin",
        )
        return resp

    async def logout(request: Request) -> Response:
        resp = RedirectResponse("/admin/login", status_code=303)
        resp.delete_cookie(_COOKIE, path="/admin")
        return resp

    # --- gated pages -----------------------------------------------------

    def _guard(handler: Any) -> Any:
        async def wrapped(request: Request) -> Response:
            principal = _session(request)
            if principal is None:
                return _redirect_login()
            ctx = _ctx(principal)
            who = principal.display or str(principal.id)
            try:
                title, active, body = await handler(request, ctx)
            except PermissionDenied as exc:
                return HTMLResponse(admin_ui.error_page(403, str(exc)), status_code=403)
            except Exception as exc:  # backend down -> degrade, don't 500
                log.warning("admin_page_error", path=request.url.path, error=str(exc))
                body = f'<div class="panel"><div class="note err">Section unavailable: {exc}</div></div>'
                title, active = "Error", request.url.path
            return HTMLResponse(admin_ui.page(title, body, active=active, who=who))

        return wrapped

    async def overview(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        org = settings.default_org_id
        members = await services.admin.list_members(ctx)
        agents = await services.admin.list_agents(ctx)
        keys = await services.api_keys.list_keys(org)
        stats = await services.vector_store.stats(org)
        body = admin_ui.cards(
            [
                ("Members", len(members)),
                ("Agents", len(agents)),
                ("API keys", len(keys)),
                ("Active memories", stats.get("active", 0)),
                ("Pending approval", stats.get("pending_approval", 0)),
                ("Quarantined", stats.get("quarantined", 0)),
            ]
        )
        return "Overview", "/admin", body

    async def members(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        rows = await services.admin.list_members(ctx)
        table = admin_ui.table(
            ["Email", "Name", "Role", "Status"],
            [[r["email"], r["display_name"], r["role"], r["status"]] for r in rows],
        )
        return "Members", "/admin/members", table

    async def agents(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        rows = await services.admin.list_agents(ctx)
        table = admin_ui.table(
            ["Name", "Kind", "Status", "Created"],
            [[r["name"], r["kind"], r["status"], r["created_at"]] for r in rows],
        )
        return "Agents", "/admin/agents", table

    async def roles(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        rows = await services.admin.list_role_bindings(ctx)
        table = admin_ui.table(
            ["Principal type", "Principal id", "Role", "Scope"],
            [
                [r.get("principal_type"), r.get("principal_id"), r.get("role"),
                 r.get("scope_type") or "org"]
                for r in rows
            ],
        )
        return "Roles", "/admin/roles", table

    async def api_keys(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        rows = await services.api_keys.list_keys(settings.default_org_id)
        table = admin_ui.table(
            ["Name", "Prefix", "Principal", "Created", "Last used", "Revoked"],
            [
                [r.get("name"), r.get("prefix"),
                 f"{r.get('principal_type')}:{r.get('principal_id')}",
                 r.get("created_at"), r.get("last_used_at"), r.get("revoked_at")]
                for r in rows
            ],
        )
        return "API keys", "/admin/api-keys", table

    async def approvals(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_APPROVE)
        rows = await services.approvals.list_pending(settings.default_org_id)
        table = admin_ui.table(
            ["Memory id", "Reason", "Created", "Content"],
            [[r["memory_id"], r["reason"], r["created_at"], r["content"]] for r in rows],
        )
        return "Pending approvals", "/admin/approvals", table

    async def audit(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        await ctx.authorizer.require(ctx.principal, Permissions.AUDIT_READ)
        rows = await services.audit.list_events(settings.default_org_id, limit=100)
        table = admin_ui.table(
            ["When", "Agent", "Action", "Actor", "Resource", "Target"],
            [
                [r["occurred_at"], r["agent"], r["action"],
                 f"{r['actor_type']}:{r['actor_id']}" if r["actor_type"] else "—",
                 r["resource_type"], r["target_id"]]
                for r in rows
            ],
        )
        return "Audit log", "/admin/audit", table

    async def retention(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        rows = await services.admin.list_retention_policies(ctx)
        table = admin_ui.table(
            ["Name", "Max age (days)", "Max items", "Kinds"],
            [[r["name"], r["max_age_days"], r["max_items"], ", ".join(r["kinds"])] for r in rows],
        )
        return "Retention policies", "/admin/retention", table

    async def connectors(request: Request, ctx: RequestContext) -> tuple[str, str, str]:
        rows = await services.connectors.list_connectors(ctx)
        table = admin_ui.table(
            ["Kind", "Name", "Status", "Created"],
            [
                [r.get("kind"), r.get("name"), r.get("status"), r.get("created_at")]
                for r in rows
            ],
        )
        return "Connectors", "/admin/connectors", table

    return [
        Route("/admin/login", login_get, methods=["GET"]),
        Route("/admin/login", login_post, methods=["POST"]),
        Route("/admin/login/verify", login_verify, methods=["GET"]),
        Route("/admin/logout", logout, methods=["GET", "POST"]),
        Route("/admin", _guard(overview), methods=["GET"]),
        Route("/admin/members", _guard(members), methods=["GET"]),
        Route("/admin/agents", _guard(agents), methods=["GET"]),
        Route("/admin/roles", _guard(roles), methods=["GET"]),
        Route("/admin/api-keys", _guard(api_keys), methods=["GET"]),
        Route("/admin/approvals", _guard(approvals), methods=["GET"]),
        Route("/admin/audit", _guard(audit), methods=["GET"]),
        Route("/admin/retention", _guard(retention), methods=["GET"]),
        Route("/admin/connectors", _guard(connectors), methods=["GET"]),
    ]
