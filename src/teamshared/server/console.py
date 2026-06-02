"""Signed-in web console at ``/app`` plus one-time-passcode (OTP) auth.

Server-rendered with Jinja2 (+ HTMX, loaded for later phases). This replaces the
old ``/admin`` tree. Humans sign in by entering their member email, receiving a
short-lived numeric OTP (stored hashed in Redis with a TTL), and submitting it;
on success they get a ``ts_session`` cookie. ``/app/*`` pages are gated by that
cookie. The console home renders live memory-system stats from the existing
stores via :func:`teamshared.server.state.get_state`.

Sections: home overview, the wiki (topics/timeline/playbooks), read screens
(memory/agents/people/keys/approvals/audit), and capture consent. Sections still
on the roadmap (settings) render a placeholder through the same shell so
navigation works end to end.
"""

from __future__ import annotations

import asyncio
import secrets
from pathlib import Path
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from teamshared.config import Settings
from teamshared.identity.principal import Principal
from teamshared.identity.provisioning import signup_org
from teamshared.identity.rbac import Permissions
from teamshared.identity.sessions import issue_session, verify_session
from teamshared.ingestion.consent import BASELINE_PROFILE, LOCKED_RULES, MODES, SCOPES
from teamshared.logging import get_logger
from teamshared.metrics import METRICS
from teamshared.memory.request_context import RequestContext
from teamshared.memory.wiki import slugify
from teamshared.server import mailer
from teamshared.server.health import check_components
from teamshared.server.rate_limit import enforce_otp_send, enforce_otp_verify
from teamshared.server.markdown_safe import render_markdown_safe
from teamshared.server.services import ProductionServices
from teamshared.server.state import get_state

log = get_logger(__name__)

_COOKIE = "ts_session"
_SESSION_TTL = 3600
_OTP_DIGITS = 6
_ORG_NAME = "TeamShared"

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# (href, label, active-key). Drives the sidebar nav in base.html.
NAV: list[tuple[str, str, str]] = [
    ("/app", "Home", "home"),
    ("/app/wiki", "Wiki", "wiki"),
    ("/app/memory", "Memory", "memory"),
    ("/app/agents", "Agents", "agents"),
    ("/app/people", "People", "people"),
    ("/app/orgs", "Organizations", "orgs"),
    ("/app/keys", "API Keys", "keys"),
    ("/app/approvals", "Approvals", "approvals"),
    ("/app/consent", "Consent", "consent"),
    ("/app/audit", "Audit", "audit"),
    ("/app/settings", "Settings", "settings"),
]

# Sections not yet built: rendered as a placeholder through the shell.
_PLACEHOLDERS: dict[str, tuple[str, str]] = {
    "/app/settings": ("settings", "Settings"),
}


def _dt(value: Any, length: int = 16) -> str:
    """Render an ISO datetime/string to a short, readable cell."""
    if not value:
        return "\u2014"
    return str(value)[:length].replace("T", " ")


def _group_by_kind(records: list[Any]) -> list[tuple[str, list[Any]]]:
    """Group memory records by kind, preserving newest-first order within each."""
    groups: dict[str, list[Any]] = {}
    for rec in records:
        key = getattr(rec, "kind", None) or "note"
        groups.setdefault(key, []).append(rec)
    return list(groups.items())


def _safe(value: Any, default: Any) -> Any:
    """Coerce a gathered store result to a usable value, tolerating failures."""
    return default if isinstance(value, BaseException) else value


async def _home_context(state: Any, org_id: Any) -> dict[str, Any]:
    """Gather live stats for the console home, degrading on per-store failure."""
    health, working, pillar, proc, events = await asyncio.gather(
        check_components(state),
        state.working.stats(org_id),
        state.services.vector_store.pillar_stats(org_id),
        state.procedural.stats(org_id),
        state.services.audit.list_events(org_id, limit=8),
        return_exceptions=True,
    )
    health = _safe(health, None)
    working = _safe(working, {})
    pillar = _safe(pillar, {})
    proc = _safe(proc, {})
    events = _safe(events, [])

    by_agent = sorted(
        (pillar.get("by_agent") or {}).items(), key=lambda kv: kv[1], reverse=True
    )
    by_agent_max = max((c for _, c in by_agent), default=1) or 1

    return {
        "health": health,
        "working_active": working.get("active", 0),
        "working_total": working.get("total", 0),
        "semantic": pillar.get("semantic", 0),
        "episodic": pillar.get("episodic", 0),
        "procedural": proc.get("playbooks", 0),
        "procedural_versions": proc.get("versions", 0),
        "by_agent": by_agent,
        "by_agent_max": by_agent_max,
        "recent": events if isinstance(events, list) else [],
    }


def register_console_routes(
    settings: Settings, services: ProductionServices
) -> list[Route]:
    """Build the console + auth route table bound to ``settings`` + ``services``."""

    def _session(request: Request) -> Principal | None:
        if not settings.session_secret:
            return None
        token = request.cookies.get(_COOKIE)
        if not token:
            return None
        return verify_session(token, secret=settings.session_secret)

    def _redirect_login() -> RedirectResponse:
        return RedirectResponse("/login", status_code=303)

    async def _org_context(principal: Principal) -> dict[str, Any]:
        """Active org name + the orgs this email can switch to (for the header)."""
        orgs: list[dict[str, Any]] = []
        if principal.display:
            try:
                orgs = await services.accounts.list_orgs(principal.display)
            except Exception as exc:
                log.warning("org_context_failed", error=str(exc))
        active = next(
            (o for o in orgs if str(o["org_id"]) == str(principal.org_id)), None
        )
        return {
            "orgs": orgs,
            "active_org_id": str(principal.org_id),
            "org_name": active["name"] if active else _ORG_NAME,
        }

    async def _shell(
        request: Request, principal: Principal, active: str
    ) -> dict[str, Any]:
        """Common template context for the console shell, incl. the org switcher."""
        ctx: dict[str, Any] = {
            "nav": NAV,
            "active": active,
            "who": principal.display or str(principal.id),
            "org_name": _ORG_NAME,
        }
        ctx.update(await _org_context(principal))
        return ctx

    def _issue_session_cookie(
        resp: Response, *, org_id: UUID, user_id: UUID, email: str
    ) -> None:
        # Only reached behind a verified session / OTP, both of which require a
        # configured secret; assert narrows the Optional for the type checker.
        assert settings.session_secret
        token = issue_session(
            secret=settings.session_secret,
            org_id=org_id,
            user_id=user_id,
            email=email,
            ttl_seconds=_SESSION_TTL,
        )
        resp.set_cookie(
            _COOKIE,
            token,
            max_age=_SESSION_TTL,
            httponly=True,
            samesite="lax",
            secure=not settings.auth_disabled,
            path="/",
        )

    # --- auth flow -------------------------------------------------------

    async def login_get(request: Request) -> Response:
        if not settings.session_secret:
            return _TEMPLATES.TemplateResponse(
                request,
                "login.html",
                {"message": "Sign-in is disabled: set TEAMSHARED_SESSION_SECRET.", "error": True},
                status_code=503,
            )
        return _TEMPLATES.TemplateResponse(request, "login.html", {})

    async def login_post(request: Request) -> Response:
        if not settings.session_secret:
            return _TEMPLATES.TemplateResponse(
                request,
                "login.html",
                {"message": "Sign-in is disabled (no session secret).", "error": True},
                status_code=503,
            )
        form = await request.form()
        email = str(form.get("email") or "").strip().lower()
        if not email:
            return _TEMPLATES.TemplateResponse(
                request, "login.html", {"message": "Email is required.", "error": True}
            )
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is not None:
            blocked = await enforce_otp_send(limiter, email)
            if blocked is not None:
                return blocked
        # Self-service: any email can sign in. We send a code to whatever was
        # entered; the email is only provisioned into an org after it verifies.
        ttl = getattr(settings, "otp_ttl_seconds", 30)
        ctx = {
            "stage": "code",
            "email": email,
            "message": f"We sent a {_OTP_DIGITS}-digit code to {email}. "
            f"It expires in {ttl}s.",
        }
        code = f"{secrets.randbelow(10**_OTP_DIGITS):0{_OTP_DIGITS}d}"
        await services.working.set_login_otp(
            email, code, ttl=ttl,
            max_attempts=getattr(settings, "otp_max_attempts", 5),
        )
        if settings.auth_disabled:
            ctx["message"] = f"Dev mode code (expires in {ttl}s):"
            ctx["otp_code"] = code
        elif mailer.smtp_configured(settings):
            # Email delivery. On failure we still render the same code screen
            # and log the error so the user can retry.
            try:
                await mailer.send_login_code(settings, email, code, ttl)
                log.info("console_login_otp_emailed", email=email, ttl=ttl)
            except Exception as exc:
                log.error("console_login_otp_email_failed", email=email, error=str(exc))
        else:
            log.warning("console_login_otp_no_delivery", email=email, ttl=ttl)
        return _TEMPLATES.TemplateResponse(request, "login.html", ctx)

    async def _signup_own_org(email: str) -> tuple[UUID, UUID]:
        """Provision a fresh personal org owned by ``email``. Returns (org, user)."""
        local = email.split("@", 1)[0] or "me"
        slug = f"{slugify(local)}-{secrets.token_hex(3)}"
        result = await signup_org(
            repo=services.tenancy,
            api_keys=services.api_keys,
            roles=services.roles,
            accounts=services.accounts,
            org_slug=slug,
            org_name=f"{local}'s org",
            owner_email=email,
        )
        return result.org_id, result.owner_user_id

    async def login_verify(request: Request) -> Response:
        if not settings.session_secret:
            return _redirect_login()
        form = await request.form()
        email = str(form.get("email") or "").strip().lower()
        code = str(form.get("code") or "").strip()
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is not None:
            blocked = await enforce_otp_verify(limiter, email)
            if blocked is not None:
                return blocked
        if not await services.working.verify_login_otp(email, code):
            METRICS.otp_failed.inc()
            return _TEMPLATES.TemplateResponse(
                request,
                "login.html",
                {"stage": "code", "email": email,
                 "message": "That code is invalid or expired.", "error": True},
                status_code=401,
            )
        # Resolve every org this email belongs to. First-time emails get their
        # own private org; returning emails land in their earliest-created org.
        try:
            orgs = await services.accounts.list_orgs(email)
            if orgs:
                active = orgs[0]
                org_id = UUID(str(active["org_id"]))
                user_id = UUID(str(active["user_id"]))
            else:
                org_id, user_id = await _signup_own_org(email)
        except Exception as exc:
            log.error("console_login_provision_failed", email=email, error=str(exc))
            return _TEMPLATES.TemplateResponse(
                request,
                "login.html",
                {"stage": "code", "email": email,
                 "message": "Sign-in failed. Please try again.", "error": True},
                status_code=500,
            )
        resp = RedirectResponse("/app", status_code=303)
        _issue_session_cookie(resp, org_id=org_id, user_id=user_id, email=email)
        log.info("console_login_ok", email=email, org_id=str(org_id))
        return resp

    async def logout(request: Request) -> Response:
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(_COOKIE, path="/")
        return resp

    # --- gated pages -----------------------------------------------------

    async def home(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "home")
        try:
            ctx.update(await _home_context(get_state(), principal.org_id))
        except RuntimeError:
            ctx.update({"health": None, "working_active": 0, "working_total": 0,
                        "semantic": 0, "episodic": 0, "procedural": 0,
                        "procedural_versions": 0, "by_agent": [], "by_agent_max": 1, "recent": []})
        return _TEMPLATES.TemplateResponse(request, "console_home.html", ctx)

    # --- wiki (Phase 4) -------------------------------------------------

    async def wiki_home(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "wiki")
        topics: list[dict[str, Any]] = []
        tags: list[Any] = []
        recent: list[Any] = []
        note = ""
        try:
            vs = services.vector_store
            subjects = await vs.list_subjects(principal.org_id, limit=100)
            topics = [
                {"subject": s["subject"], "slug": slugify(s["subject"]),
                 "count": s["count"], "updated": _dt(s.get("updated_at"), 10)}
                for s in subjects
            ]
            stats = await vs.pillar_stats(principal.org_id)
            tags = stats.get("tags", [])
            recent = await vs.list_recent(principal.org_id, limit=8, pillar="semantic")
        except Exception as exc:
            log.warning("wiki_home_failed", error=str(exc))
            note = f"Wiki unavailable: {exc}"
        ctx.update({"topics": topics, "tags": tags, "recent": recent, "note": note})
        return _TEMPLATES.TemplateResponse(request, "wiki_home.html", ctx)

    async def wiki_topic(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "wiki")
        slug = str(request.path_params["slug"])
        subject: str | None = None
        groups: list[tuple[str, list[Any]]] = []
        curated_html = ""
        curated: dict[str, Any] | None = None
        note = ""
        try:
            vs = services.vector_store
            subjects = await vs.list_subjects(principal.org_id, limit=500)
            slug_map = {slugify(s["subject"]): s["subject"] for s in subjects}
            subject = slug_map.get(slug)
            if subject is None:
                note = "Topic not found."
            else:
                records = await vs.list_by_subject(principal.org_id, subject, limit=200)
                groups = _group_by_kind(records)
                curated = await services.wiki.get_page(principal.org_id, slug)
                if curated:
                    curated_html = render_markdown_safe(curated.get("body_md") or "")
        except Exception as exc:
            log.warning("wiki_topic_failed", error=str(exc))
            note = f"Wiki unavailable: {exc}"
        ctx.update(
            {
                "subject": subject, "groups": groups, "note": note,
                "curated_html": curated_html,
                "curated_version": curated.get("version") if curated else None,
                "curated_updated": _dt(curated.get("updated_at")) if curated else "",
            }
        )
        return _TEMPLATES.TemplateResponse(request, "wiki_topic.html", ctx)

    async def wiki_timeline(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "wiki")
        entries: list[Any] = []
        note = ""
        try:
            entries = await services.vector_store.list_episodes(
                org_id=principal.org_id, limit=50
            )
        except Exception as exc:
            log.warning("wiki_timeline_failed", error=str(exc))
            note = f"Wiki unavailable: {exc}"
        ctx.update({"entries": entries, "note": note})
        return _TEMPLATES.TemplateResponse(request, "wiki_timeline.html", ctx)

    async def wiki_playbooks(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "wiki")
        playbooks: list[dict[str, Any]] = []
        note = ""
        try:
            procs = await services.procedural.list_procedures(principal.org_id, limit=100)
            playbooks = [
                {
                    "name": p["name"], "version": p["version"],
                    "description": p.get("description"), "tags": p.get("tags") or [],
                    "body_html": render_markdown_safe(p.get("steps_md") or ""),
                }
                for p in procs
            ]
        except Exception as exc:
            log.warning("wiki_playbooks_failed", error=str(exc))
            note = f"Wiki unavailable: {exc}"
        ctx.update({"playbooks": playbooks, "note": note})
        return _TEMPLATES.TemplateResponse(request, "wiki_playbooks.html", ctx)

    # --- read screens (Phase 3) -----------------------------------------

    def _ctx(principal: Principal) -> RequestContext:
        return RequestContext(
            principal=principal, db=services.tenant_db, authorizer=services.authorizer()
        )

    async def _table(
        request: Request,
        principal: Principal,
        *,
        active: str,
        title: str,
        subtitle: str,
        headers: list[str],
        rows: list[list[str]],
        note: str,
    ) -> Response:
        ctx = await _shell(request, principal, active)
        ctx.update(
            {"section_title": title, "subtitle": subtitle, "headers": headers,
             "rows": rows, "note": note}
        )
        return _TEMPLATES.TemplateResponse(request, "table_page.html", ctx)

    async def memory_explorer(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "memory")
        q = request.query_params.get("q", "").strip()
        pillar = request.query_params.get("pillar", "").strip() or None
        records: list[Any] = []
        note = ""
        try:
            vs = services.vector_store
            if q:
                scope_filter = await _ctx(principal).accessible_scope_filter()
                records = await vs.keyword_search(
                    org_id=principal.org_id, query=q, scope_filter=scope_filter, k=25
                )
                if pillar:
                    records = [r for r in records if r.pillar == pillar]
            else:
                records = await vs.list_recent(principal.org_id, limit=25, pillar=pillar)
        except Exception as exc:
            log.warning("memory_explorer_failed", error=str(exc))
            note = f"Memory unavailable: {exc}"
        ctx.update({"q": q, "pillar": pillar or "", "records": records, "note": note})
        return _TEMPLATES.TemplateResponse(request, "memory.html", ctx)

    async def memory_detail(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "memory")
        item: Any = None
        note = ""
        try:
            memory_id = UUID(str(request.path_params["memory_id"]))
            item = await services.vector_store.get(principal.org_id, memory_id)
            if item is None:
                note = "Memory not found."
        except ValueError:
            note = "Memory not found."
        except Exception as exc:
            log.warning("memory_detail_failed", error=str(exc))
            note = f"Memory unavailable: {exc}"
        ctx.update({"item": item, "note": note})
        return _TEMPLATES.TemplateResponse(request, "memory_detail.html", ctx)

    async def _list_agents_view(principal: Principal) -> tuple[list[dict[str, Any]], str]:
        try:
            data = await services.admin.list_agents(_ctx(principal))
            agents = [
                {"id": d["id"], "name": d["name"], "kind": d["kind"],
                 "status": d["status"], "created": _dt(d.get("created_at"), 10)}
                for d in data
            ]
            return agents, ""
        except Exception as exc:
            log.warning("agents_page_failed", error=str(exc))
            return [], f"Unavailable: {exc}"

    async def agents_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "agents")
        agents, note = await _list_agents_view(principal)
        ctx.update({"agents": agents, "note": note})
        return _TEMPLATES.TemplateResponse(request, "agents.html", ctx)

    async def agent_add(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form = await request.form()
        name = str(form.get("name") or "").strip()
        if name:
            try:
                await services.admin.create_agent(_ctx(principal), name=name)
            except Exception as exc:
                log.warning("agent_add_failed", error=str(exc))
        return RedirectResponse("/app/agents", status_code=303)

    async def agent_status(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form = await request.form()
        status = str(form.get("status") or "").strip()
        try:
            await services.admin.set_agent_status(
                _ctx(principal), UUID(str(request.path_params["agent_id"])), status
            )
        except Exception as exc:
            log.warning("agent_status_failed", error=str(exc))
        return RedirectResponse("/app/agents", status_code=303)

    async def people_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "people")
        members: list[dict[str, Any]] = []
        bindings: list[dict[str, Any]] = []
        note = ""
        try:
            rctx = _ctx(principal)
            members = await services.admin.list_members(rctx)
            bindings = await services.admin.list_role_bindings(rctx)
        except Exception as exc:
            log.warning("people_page_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        ctx.update(
            {"members": members, "bindings": bindings, "note": note,
             "roles": ["org_admin", "member", "viewer", "agent"]}
        )
        return _TEMPLATES.TemplateResponse(request, "people.html", ctx)

    async def people_grant(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form = await request.form()
        pid = str(form.get("principal_id") or "").strip()
        role_name = str(form.get("role_name") or "").strip()
        try:
            await services.admin.grant_role(
                _ctx(principal), principal_type="user",
                principal_id=UUID(pid), role_name=role_name,
            )
        except Exception as exc:
            log.warning("people_grant_failed", error=str(exc))
        return RedirectResponse("/app/people", status_code=303)

    async def people_revoke(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form = await request.form()
        ptype = str(form.get("principal_type") or "").strip()
        pid = str(form.get("principal_id") or "").strip()
        role_name = str(form.get("role_name") or "").strip()
        try:
            await services.admin.revoke_role(
                _ctx(principal), principal_type=ptype,  # type: ignore[arg-type]
                principal_id=UUID(pid), role_name=role_name,
            )
        except Exception as exc:
            log.warning("people_revoke_failed", error=str(exc))
        return RedirectResponse("/app/people", status_code=303)

    async def people_add(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form = await request.form()
        email = str(form.get("email") or "").strip().lower()
        role = str(form.get("role") or "member").strip() or "member"
        if email:
            try:
                await services.admin.add_member(_ctx(principal), email=email, role=role)
            except Exception as exc:
                log.warning("people_add_failed", error=str(exc))
        return RedirectResponse("/app/people", status_code=303)

    # --- organizations (org switcher + self-service create) --------------

    async def orgs_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "orgs")
        return _TEMPLATES.TemplateResponse(request, "orgs.html", ctx)

    async def org_create(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        if not principal.display:
            return _redirect_login()
        form = await request.form()
        name = str(form.get("name") or "").strip()
        resp = RedirectResponse("/app", status_code=303)
        if not name:
            return RedirectResponse("/app/orgs", status_code=303)
        try:
            slug = f"{slugify(name) or 'org'}-{secrets.token_hex(3)}"
            result = await signup_org(
                repo=services.tenancy, api_keys=services.api_keys, roles=services.roles,
                accounts=services.accounts, org_slug=slug, org_name=name,
                owner_email=principal.display,
            )
            _issue_session_cookie(
                resp, org_id=result.org_id, user_id=result.owner_user_id,
                email=principal.display,
            )
        except Exception as exc:
            log.warning("org_create_failed", error=str(exc))
            return RedirectResponse("/app/orgs", status_code=303)
        return resp

    async def org_switch(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        email = principal.display
        if not email:
            return _redirect_login()
        form = await request.form()
        target = str(form.get("org_id") or "").strip()
        # Re-issue the session only for an org the email actually belongs to.
        try:
            orgs = await services.accounts.list_orgs(email)
        except Exception as exc:
            log.warning("org_switch_lookup_failed", error=str(exc))
            return RedirectResponse("/app/orgs", status_code=303)
        match = next((o for o in orgs if str(o["org_id"]) == target), None)
        if match is None:
            return RedirectResponse("/app/orgs", status_code=303)
        resp = RedirectResponse("/app", status_code=303)
        _issue_session_cookie(
            resp, org_id=UUID(str(match["org_id"])),
            user_id=UUID(str(match["user_id"])), email=email,
        )
        return resp

    def _key_rows(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "id": d.get("id"), "name": str(d.get("name") or "\u2014"),
                "prefix": str(d.get("prefix") or "\u2014"),
                "principal": f"{d.get('principal_type')}:{d.get('principal_id')}",
                "created": _dt(d.get("created_at")), "last_used": _dt(d.get("last_used_at")),
                "revoked": bool(d.get("revoked") or d.get("revoked_at")),
            }
            for d in data
        ]

    async def keys_page(request: Request, *, new_token: str = "", note: str = "") -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "keys")
        keys: list[dict[str, Any]] = []
        agents: list[dict[str, Any]] = []
        try:
            keys = _key_rows(await services.api_keys.list_keys(principal.org_id))
            agents, _ = await _list_agents_view(principal)
        except Exception as exc:
            log.warning("keys_page_failed", error=str(exc))
            note = note or f"Unavailable: {exc}"
        ctx.update({"keys": keys, "agents": agents, "new_token": new_token, "note": note})
        return _TEMPLATES.TemplateResponse(request, "keys.html", ctx)

    async def key_mint(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form = await request.form()
        agent_id = str(form.get("agent_id") or "").strip()
        name = str(form.get("name") or "").strip() or "api-key"
        new_token = ""
        note = ""
        try:
            ctx = _ctx(principal)
            await ctx.authorizer.require(principal, Permissions.ORG_ADMIN)
            minted = await services.api_keys.mint(
                org_id=principal.org_id, principal_type="agent",
                principal_id=UUID(agent_id), name=name, created_by=principal.id,
            )
            new_token = minted.token
        except Exception as exc:
            log.warning("key_mint_failed", error=str(exc))
            note = f"Could not mint key: {exc}"
        return await keys_page(request, new_token=new_token, note=note)

    async def key_revoke(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        try:
            ctx = _ctx(principal)
            await ctx.authorizer.require(principal, Permissions.ORG_ADMIN)
            await services.api_keys.revoke(
                principal.org_id, UUID(str(request.path_params["key_id"]))
            )
        except Exception as exc:
            log.warning("key_revoke_failed", error=str(exc))
        return RedirectResponse("/app/keys", status_code=303)

    async def approvals_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "approvals")
        pending: list[dict[str, Any]] = []
        note = ""
        try:
            data = await services.approvals.list_pending(principal.org_id)
            pending = [
                {"id": d.get("id"), "created": _dt(d.get("created_at")),
                 "reason": d.get("reason") or "\u2014", "content": d.get("content") or ""}
                for d in data
            ]
        except Exception as exc:
            log.warning("approvals_page_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        ctx.update({"pending": pending, "note": note})
        return _TEMPLATES.TemplateResponse(request, "approvals.html", ctx)

    async def approval_decide(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form = await request.form()
        approved = str(form.get("decision") or "").strip() == "approve"
        try:
            ctx = _ctx(principal)
            await ctx.authorizer.require(principal, Permissions.MEMORY_APPROVE)
            memory_id = await services.approvals.decide(
                principal.org_id, UUID(str(request.path_params["approval_id"])),
                approved=approved, decided_by=principal.id,
            )
            await services.audit.record(
                agent=principal.attribution, action="memory.approve", org_id=principal.org_id,
                actor_type=principal.type, actor_id=principal.id, resource_type="memory",
                target_id=str(memory_id) if memory_id else None, request_id=ctx.request_id,
                after={"approved": approved},
            )
        except Exception as exc:
            log.warning("approval_decide_failed", error=str(exc))
        return RedirectResponse("/app/approvals", status_code=303)

    async def audit_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        rows: list[list[str]] = []
        note = ""
        try:
            data = await services.audit.list_events(principal.org_id, limit=100)
            rows = [
                [_dt(d.get("occurred_at")), d.get("agent") or "\u2014",
                 d.get("action") or "\u2014",
                 d.get("resource_type") or "\u2014", d.get("target_id") or "\u2014"]
                for d in data
            ]
        except Exception as exc:
            log.warning("audit_page_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        return await _table(
            request, principal, active="audit", title="Audit log",
            subtitle="Every read, write, share, and permission change.",
            headers=["When", "Agent", "Action", "Resource", "Target"], rows=rows, note=note,
        )

    # --- consent (Phase 2) ----------------------------------------------

    async def consent_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "consent")
        try:
            grants = await services.consent.list_grants(principal.org_id)
        except Exception as exc:
            log.warning("consent_list_failed", error=str(exc))
            grants = []
        ctx.update(
            {
                "grants": grants,
                "scopes": SCOPES,
                "modes": MODES,
                "baseline": BASELINE_PROFILE,
                "locked": LOCKED_RULES,
            }
        )
        return _TEMPLATES.TemplateResponse(request, "consent.html", ctx)

    async def consent_grant(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form = await request.form()
        agent = str(form.get("agent") or "").strip()
        mode = str(form.get("mode") or "review")
        scope = [str(s) for s in form.getlist("scope")]
        if agent and mode in MODES:
            try:
                await services.consent.grant(
                    principal.org_id,
                    agent=agent,
                    mode=mode,
                    scope=scope,
                    granted_by=principal.id,
                )
            except Exception as exc:
                log.warning("consent_grant_failed", error=str(exc))
        return RedirectResponse("/app/consent", status_code=303)

    async def consent_revoke(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        grant_id = request.path_params["grant_id"]
        try:
            await services.consent.revoke(principal.org_id, grant_id)
        except Exception as exc:
            log.warning("consent_revoke_failed", error=str(exc))
        return RedirectResponse("/app/consent", status_code=303)

    def _placeholder(active: str, title: str) -> Any:
        async def handler(request: Request) -> Response:
            principal = _session(request)
            if principal is None:
                return _redirect_login()
            ctx = await _shell(request, principal, active)
            ctx["section_title"] = title
            return _TEMPLATES.TemplateResponse(request, "placeholder.html", ctx)

        return handler

    routes = [
        Route("/login", login_get, methods=["GET"]),
        Route("/login", login_post, methods=["POST"]),
        Route("/login/verify", login_verify, methods=["POST"]),
        Route("/logout", logout, methods=["GET", "POST"]),
        Route("/app", home, methods=["GET"]),
        Route("/app/wiki", wiki_home, methods=["GET"]),
        Route("/app/wiki/timeline", wiki_timeline, methods=["GET"]),
        Route("/app/wiki/playbooks", wiki_playbooks, methods=["GET"]),
        Route("/app/wiki/topic/{slug}", wiki_topic, methods=["GET"]),
        Route("/app/memory", memory_explorer, methods=["GET"]),
        Route("/app/memory/{memory_id}", memory_detail, methods=["GET"]),
        Route("/app/agents", agents_page, methods=["GET"]),
        Route("/app/agents/add", agent_add, methods=["POST"]),
        Route("/app/agents/{agent_id}/status", agent_status, methods=["POST"]),
        Route("/app/people", people_page, methods=["GET"]),
        Route("/app/people/add", people_add, methods=["POST"]),
        Route("/app/people/grant", people_grant, methods=["POST"]),
        Route("/app/people/revoke", people_revoke, methods=["POST"]),
        Route("/app/orgs", orgs_page, methods=["GET"]),
        Route("/app/orgs/create", org_create, methods=["POST"]),
        Route("/app/orgs/switch", org_switch, methods=["POST"]),
        Route("/app/keys", keys_page, methods=["GET"]),
        Route("/app/keys/mint", key_mint, methods=["POST"]),
        Route("/app/keys/{key_id}/revoke", key_revoke, methods=["POST"]),
        Route("/app/approvals", approvals_page, methods=["GET"]),
        Route("/app/approvals/{approval_id}/decide", approval_decide, methods=["POST"]),
        Route("/app/audit", audit_page, methods=["GET"]),
        Route("/app/consent", consent_page, methods=["GET"]),
        Route("/app/consent/grant", consent_grant, methods=["POST"]),
        Route("/app/consent/{grant_id}/revoke", consent_revoke, methods=["POST"]),
    ]
    for path, (active, title) in _PLACEHOLDERS.items():
        routes.append(Route(path, _placeholder(active, title), methods=["GET"]))
    return routes
