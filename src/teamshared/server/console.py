"""Signed-in web console at ``/app`` plus one-time-passcode (OTP) auth.

Server-rendered with Jinja2 (+ HTMX, loaded for later phases). This replaces the
old ``/admin`` tree. Humans sign in by entering their member email, receiving a
short-lived numeric OTP (stored hashed in Redis with a TTL), and submitting it;
on success they get a ``ts_session`` cookie. ``/app/*`` pages are gated by that
cookie. The console home renders live memory-system stats from the existing
stores via :func:`teamshared.server.state.get_state`.

Sections: home overview, the wiki (topics/timeline/playbooks), read screens
(memory/agents), govern surfaces (people/orgs/keys/audit). Sections still
unbuilt render a placeholder through the same shell so navigation works end
to end.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any
from uuid import UUID

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from teamshared import __version__
from teamshared.admin.service import AdminService
from teamshared.clients.agent_setup import canonical_install_script_url
from teamshared.config import Settings
from teamshared.identity.principal import Principal
from teamshared.identity.provisioning import signup_org
from teamshared.identity.rbac import PermissionDenied, Permissions
from teamshared.identity.sessions import issue_session, verify_session
from teamshared.logging import get_logger
from teamshared.memory.request_context import RequestContext
from teamshared.memory.wiki import slugify
from teamshared.metrics import METRICS
from teamshared.playbook.compose import (
    build_skill_recipe,
    skill_names_from_recipe,
)
from teamshared.server import mailer
from teamshared.server.console_csrf import (
    cookie_secure,
    csrf_failure_reason,
    csrf_token_for_principal,
    verify_console_csrf,
)
from teamshared.server.health import check_components
from teamshared.server.markdown_safe import render_markdown_safe
from teamshared.server.rate_limit import (
    enforce_admin_export,
    enforce_admin_purge,
    enforce_otp_send,
    enforce_otp_verify,
)
from teamshared.server.services import ProductionServices
from teamshared.server.state import get_state

log = get_logger(__name__)

_COOKIE = "ts_session"
_OTP_DIGITS = 6
_ORG_NAME = "TeamShared"

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _asset_version() -> str:
    """Short content hash of console.css for cache-busting the stylesheet link.

    The static assets are served with a 24h ``Cache-Control``; without a
    version query the browser keeps serving a stale stylesheet after a deploy.
    """
    css = Path(__file__).parent / "static" / "console.css"
    try:
        digest = hashlib.sha256(css.read_bytes()).hexdigest()
    except OSError:
        return "0"
    return digest[:12]


_TEMPLATES.env.globals["asset_version"] = _asset_version()

# (href, label, active-key). Drives the sidebar nav in base.html.
NAV: list[tuple[str, str, str]] = [
    ("/app", "Home", "home"),
    ("/app/wiki", "Wiki", "wiki"),
    ("/app/playbooks", "Playbooks", "playbooks"),
    ("/app/skills", "Skills", "skills"),
    ("/app/work", "Work", "work"),
    ("/app/projects", "Projects", "projects"),
    ("/app/strategy", "Strategy", "strategy"),
    ("/app/memory", "Memory", "memory"),
    ("/app/people", "People", "people"),
    ("/app/orgs", "Organizations", "orgs"),
    ("/app/keys", "API Keys", "keys"),
    ("/app/audit", "Audit", "audit"),
    ("/app/settings", "Settings", "settings"),
]

NAV_GROUPS: list[tuple[str | None, list[tuple[str, str, str]]]] = [
    (None, [("/app", "Home", "home")]),
    (
        "Memory",
        [
            ("/app/wiki", "Wiki", "wiki"),
            ("/app/ontology", "Ontology", "ontology"),
            ("/app/playbooks", "Playbooks", "playbooks"),
            ("/app/skills", "Skills", "skills"),
            ("/app/memory", "Explorer", "memory"),
        ],
    ),
    (
        "Work",
        [
            ("/app/work", "Tasks", "work"),
            ("/app/projects", "Projects", "projects"),
            ("/app/strategy", "Strategy", "strategy"),
        ],
    ),
    (
        "Govern",
        [
            ("/app/people", "People", "people"),
            ("/app/orgs", "Organizations", "orgs"),
            ("/app/keys", "API Keys", "keys"),
            ("/app/connections", "Connections", "connections"),
            ("/app/ontology", "Ontology", "ontology"),
            ("/app/audit", "Audit", "audit"),
            ("/app/settings", "Settings", "settings"),
        ],
    ),
]

# Sections not yet built: rendered as a placeholder through the shell.
_PLACEHOLDERS: dict[str, tuple[str, str]] = {}


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


def _nest_subtasks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a flat work list into top-level tasks with nested ``subtasks``.

    A subtask (``parent_id`` set) is attached to its parent's ``subtasks`` list
    when the parent is present in the same result set; otherwise it surfaces as
    a top-level row so filtered views never silently drop it.
    """
    by_id = {str(i["id"]): i for i in items if i.get("id")}
    for item in items:
        item.setdefault("subtasks", [])
    roots: list[dict[str, Any]] = []
    for item in items:
        parent_id = item.get("parent_id")
        parent = by_id.get(str(parent_id)) if parent_id else None
        if parent is not None and parent is not item:
            parent["subtasks"].append(item)
        else:
            roots.append(item)
    return roots


async def _settings_context(
    state: Any,
    *,
    principal: Principal | None = None,
    services: ProductionServices | None = None,
) -> dict[str, Any]:
    """Probe deployment health and data-portability controls for settings."""
    try:
        health = await check_components(state)
    except Exception as exc:
        log.warning("settings_health_failed", error=str(exc))
        health = None
    ctx: dict[str, Any] = {"health": health, "can_export": False, "can_purge": False,
                           "members": [], "export_max_items": 50_000}
    if principal is None or services is None:
        return ctx
    authorizer = services.authorizer()
    ctx["can_export"] = await authorizer.has(principal, Permissions.MEMORY_EXPORT)
    ctx["can_purge"] = await authorizer.has(principal, Permissions.MEMORY_ADMIN)
    ctx["export_max_items"] = services.admin.export_max_items
    if ctx["can_purge"]:
        try:
            rctx = RequestContext(
                principal=principal, db=services.tenant_db, authorizer=authorizer
            )
            ctx["members"] = await services.admin.list_members_for_erasure(rctx)
        except Exception as exc:
            log.warning("settings_members_failed", error=str(exc))
            ctx["members"] = []
    return ctx


async def _home_context(state: Any, org_id: Any) -> dict[str, Any]:
    """Gather live stats for the console home, degrading on per-store failure."""
    results = await asyncio.gather(
        state.working.stats(org_id),
        state.services.vector_store.pillar_stats(org_id),
        state.procedural.stats(org_id),
        state.services.strategic.stats(org_id),
        state.services.work.stats(org_id),
        state.services.audit.list_events(org_id, limit=8),
        state.services.audit.recall_metrics(org_id),
        state.services.api_keys.list_keys(org_id),
        return_exceptions=True,
    )
    working = _safe(results[0], {})
    pillar = _safe(results[1], {})
    proc = _safe(results[2], {})
    strat = _safe(results[3], {})
    work = _safe(results[4], {})
    events = _safe(results[5], [])
    recall = _safe(results[6], {})
    api_keys = _safe(results[7], [])

    by_agent = sorted(
        (pillar.get("by_agent") or {}).items(), key=lambda kv: kv[1], reverse=True
    )
    by_agent_max = max((c for _, c in by_agent), default=1) or 1
    active_keys = [key for key in api_keys if not key.get("revoked_at")]
    onboarding_steps = [
        {"label": "Mint an API key", "done": bool(active_keys), "href": "/app/keys"},
        {
            "label": "Connect an agent",
            "done": any(key.get("last_used_at") for key in active_keys),
            "href": "/app/keys",
        },
        {
            "label": "Write the first memory",
            "done": (pillar.get("semantic", 0) + pillar.get("episodic", 0)) > 0,
            "href": "/app/memory",
        },
        {
            "label": "Connect a second agent",
            "done": recall.get("active_agents", 0) >= 2,
            "href": "/app/people",
        },
        {
            "label": "Complete a cross-agent recall",
            "done": recall.get("cross_agent_recalls", 0) > 0,
            "href": "/app/memory",
        },
    ]

    return {
        "working_active": working.get("active", 0),
        "working_total": working.get("total", 0),
        "semantic": pillar.get("semantic", 0),
        "episodic": pillar.get("episodic", 0),
        "procedural": proc.get("playbooks", 0),
        "procedural_versions": proc.get("versions", 0),
        "strategic_plans": strat.get("plans", 0),
        "strategic_objectives": strat.get("objectives", 0),
        "work_open": work.get("open", 0),
        "work_blocked": work.get("blocked", 0),
        "by_agent": by_agent,
        "by_agent_max": by_agent_max,
        "recent": events if isinstance(events, list) else [],
        "recall_metrics": recall,
        "onboarding_steps": onboarding_steps,
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
            "nav_groups": NAV_GROUPS,
            "active": active,
            "who": principal.display or str(principal.id),
            "org_name": _ORG_NAME,
            "app_version": __version__,
        }
        ctx.update(await _org_context(principal))
        secret = settings.session_secret or ""
        if secret:
            ctx["csrf_token"] = csrf_token_for_principal(
                principal.org_id, principal.id, secret
            )
        else:
            ctx["csrf_token"] = ""
        return ctx

    def _csrf_failed(request: Request) -> Response:
        return _TEMPLATES.TemplateResponse(
            request,
            "csrf_failed.html",
            {"nav": NAV, "nav_groups": NAV_GROUPS, "active": "", "csrf_token": ""},
            status_code=403,
        )

    async def _verified_form(request: Request) -> tuple[Any, Response | None]:
        """Parse a console POST form after CSRF validation."""
        form = await request.form()
        session = request.cookies.get(_COOKIE, "")
        secret = settings.session_secret or ""
        token = str(form.get("csrf_token") or "")
        principal = _session(request)
        if not verify_console_csrf(
            session,
            secret,
            token,
            csrf_cookie=request.cookies.get("ts_csrf"),
            org_id=principal.org_id if principal else None,
            user_id=principal.id if principal else None,
        ):
            log.warning(
                "console_csrf_rejected",
                path=request.url.path,
                reason=csrf_failure_reason(
                    session, secret, token, request.cookies.get("ts_csrf")
                ),
                has_csrf_cookie=bool(request.cookies.get("ts_csrf")),
            )
            return form, _csrf_failed(request)
        return form, None

    async def _issue_session_cookie(
        request: Request,
        resp: Response,
        *,
        org_id: UUID,
        user_id: UUID,
        email: str,
        account_id: UUID | None = None,
    ) -> None:
        # Only reached behind a verified session / OTP, both of which require a
        # configured secret; assert narrows the Optional for the type checker.
        assert settings.session_secret
        ttl = settings.console_session_ttl
        resolved_account = account_id
        if resolved_account is None:
            try:
                resolved_account = await services.accounts.upsert(email)
            except Exception as exc:
                log.warning("session_account_resolve_failed", error=str(exc))
        token = issue_session(
            secret=settings.session_secret,
            org_id=org_id,
            user_id=user_id,
            email=email,
            account_id=resolved_account,
            ttl_seconds=ttl,
        )
        resp.set_cookie(
            _COOKIE,
            token,
            max_age=ttl,
            httponly=True,
            samesite="lax",
            secure=cookie_secure(request, auth_disabled=settings.auth_disabled),
            path="/",
        )
        if settings.session_secret:
            csrf = csrf_token_for_principal(org_id, user_id, settings.session_secret)
            resp.set_cookie(
                "ts_csrf",
                csrf,
                max_age=ttl,
                httponly=False,
                samesite="lax",
                secure=cookie_secure(request, auth_disabled=settings.auth_disabled),
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
        await _issue_session_cookie(
            request, resp, org_id=org_id, user_id=user_id, email=email
        )
        log.info("console_login_ok", email=email, org_id=str(org_id))
        return resp

    async def logout(request: Request) -> Response:
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(_COOKIE, path="/")
        resp.delete_cookie("ts_csrf", path="/")
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
            ctx.update({"working_active": 0, "working_total": 0,
                        "work_open": 0, "work_blocked": 0,
                        "semantic": 0, "episodic": 0, "procedural": 0,
                        "procedural_versions": 0, "by_agent": [], "by_agent_max": 1,
                        "recent": [], "recall_metrics": {}, "onboarding_steps": []})
        return _TEMPLATES.TemplateResponse(request, "console_home.html", ctx)

    async def settings_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "settings")
        try:
            ctx.update(
                await _settings_context(
                    get_state(), principal=principal, services=services
                )
            )
        except RuntimeError:
            ctx.update({"health": None, "can_export": False, "can_purge": False,
                        "members": []})
        purged = request.query_params.get("purged")
        if purged is not None:
            ctx["flash"] = f"Soft-deleted {purged} memory item(s) for that user."
        return _TEMPLATES.TemplateResponse(request, "console_settings.html", ctx)

    async def settings_export(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is not None:
            blocked = await enforce_admin_export(limiter, principal)
            if blocked is not None:
                return blocked
        rctx = _ctx(principal)
        try:
            payload = await services.admin.export_memory(rctx)
        except Exception as exc:
            log.warning("settings_export_failed", error=str(exc))
            return JSONResponse({"error": str(exc)}, status_code=400)
        body = AdminService.export_to_json(payload)
        filename = f"teamshared-export-{principal.org_id}.json"
        return Response(
            body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    async def settings_purge(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, failed = await _verified_form(request)
        if failed is not None:
            return failed
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is not None:
            blocked = await enforce_admin_purge(limiter, principal)
            if blocked is not None:
                return blocked
        if str(form.get("confirm_erase") or "") != "yes":
            return RedirectResponse("/app/settings?error=confirm", status_code=303)
        user_raw = str(form.get("user_id") or "").strip()
        try:
            user_id = UUID(user_raw)
        except ValueError:
            return RedirectResponse("/app/settings?error=user", status_code=303)
        rctx = _ctx(principal)
        try:
            deleted = await services.admin.purge_user_memory(rctx, user_id)
        except Exception as exc:
            log.warning("settings_purge_failed", error=str(exc))
            return RedirectResponse("/app/settings?error=purge", status_code=303)
        return RedirectResponse(f"/app/settings?purged={deleted}", status_code=303)

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
        ctx["flash"] = request.query_params.get("flash") or ""
        slug = str(request.path_params["slug"])
        subject: str | None = None
        groups: list[tuple[str, list[Any]]] = []
        curated_html = ""
        curated: dict[str, Any] | None = None
        entity: dict[str, Any] | None = None
        related_skills: list[dict[str, Any]] = []
        related_playbooks: list[dict[str, Any]] = []
        note = ""
        try:
            vs = services.vector_store
            entity = await services.ontology.get_entity_by_slug(principal.org_id, slug)
            subjects = await vs.list_subjects(principal.org_id, limit=500)
            slug_map = {slugify(s["subject"]): s["subject"] for s in subjects}
            subject = slug_map.get(slug)
            if subject is None and entity is not None:
                subject = str(entity.get("name") or slug)
            if subject is None and entity is None:
                note = "Topic not found."
            else:
                if subject is not None:
                    records = await vs.list_by_subject(principal.org_id, subject, limit=200)
                    groups = _group_by_kind(records)
                curated = await services.wiki.get_page(principal.org_id, slug)
                if curated:
                    curated_html = render_markdown_safe(curated.get("body_md") or "")
                if subject or entity:
                    related_skills, related_playbooks = (
                        await get_state().facade.related_skills_playbooks(
                            principal.org_id,
                            slug=slug,
                            subject=subject,
                        )
                    )
        except Exception as exc:
            log.warning("wiki_topic_failed", error=str(exc))
            note = f"Wiki unavailable: {exc}"
        ctx.update(
            {
                "slug": slug,
                "subject": subject,
                "entity": entity,
                "groups": groups,
                "note": note,
                "curated_html": curated_html,
                "curated_version": curated.get("version") if curated else None,
                "curated_updated": _dt(curated.get("updated_at")) if curated else "",
                "related_skills": related_skills,
                "related_playbooks": related_playbooks,
            }
        )
        return _TEMPLATES.TemplateResponse(request, "wiki_topic.html", ctx)

    async def wiki_edit(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "wiki")
        slug = str(request.path_params["slug"])
        body_md = ""
        curated: dict[str, Any] | None = None
        subject: str | None = None
        note = ""
        try:
            curated = await services.wiki.get_page(principal.org_id, slug)
            if curated:
                body_md = curated.get("body_md") or ""
            entity = await services.ontology.get_entity_by_slug(principal.org_id, slug)
            if entity:
                subject = str(entity.get("name") or slug)
            else:
                subjects = await services.vector_store.list_subjects(principal.org_id, limit=500)
                slug_map = {slugify(s["subject"]): s["subject"] for s in subjects}
                subject = slug_map.get(slug)
            if subject is None:
                subject = slug
        except Exception as exc:
            log.warning("wiki_edit_failed", error=str(exc))
            note = f"Wiki unavailable: {exc}"
        ctx.update(
            {
                "slug": slug,
                "subject": subject,
                "body_md": body_md,
                "note": note,
                "curated_version": curated.get("version") if curated else None,
            }
        )
        return _TEMPLATES.TemplateResponse(request, "wiki_edit.html", ctx)

    async def wiki_edit_save(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        slug = str(form.get("slug") or request.path_params.get("slug") or "").strip()
        body_md = str(form.get("body_md") or "").strip()
        if not slug:
            return RedirectResponse("/app/wiki?flash=invalid", status_code=303)
        try:
            ctx = _ctx(principal)
            existing = await services.wiki.get_page(principal.org_id, slug)
            required_perm = Permissions.MEMORY_UPDATE if existing else Permissions.MEMORY_CREATE
            await ctx.authorizer.require(principal, required_perm)

            subject: str | None = None
            entity = await services.ontology.get_entity_by_slug(principal.org_id, slug)
            if entity:
                subject = str(entity.get("name") or slug)
            else:
                subjects = await services.vector_store.list_subjects(principal.org_id, limit=500)
                slug_map = {slugify(s["subject"]): s["subject"] for s in subjects}
                subject = slug_map.get(slug)
            if subject is None:
                subject = slug

            title = str(form.get("title") or subject or slug).strip()
            sources: list[str] = []
            if existing:
                sources = [str(s) for s in (existing.get("sources") or [])]

            await services.wiki.upsert_page(
                principal.org_id,
                slug=slug,
                title=title,
                body_md=body_md,
                sources=sources,
                updated_by=principal.display or str(principal.id),
            )
        except PermissionDenied:
            return RedirectResponse(f"/app/wiki/topic/{slug}?flash=permission", status_code=303)
        except Exception as exc:
            log.warning("wiki_save_failed", error=str(exc))
            return RedirectResponse(f"/app/wiki/topic/{slug}?flash=error", status_code=303)
        return RedirectResponse(f"/app/wiki/topic/{slug}?flash=saved", status_code=303)

    async def entity_hub(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "wiki")
        slug = str(request.path_params["slug"])
        subject: str | None = None
        groups: list[tuple[str, list[Any]]] = []
        curated_html = ""
        curated: dict[str, Any] | None = None
        graph_records: list[Any] = []
        work_items: list[dict[str, Any]] = []
        episodes: list[dict[str, Any]] = []
        related_skills: list[dict[str, Any]] = []
        related_playbooks: list[dict[str, Any]] = []
        entity: dict[str, Any] | None = None
        note = ""
        try:
            pack = await get_state().facade.entity_view(principal, slug=slug)
            subject = pack.get("subject")
            note = pack.get("note") or ""
            entity = pack.get("entity")
            wiki = pack.get("wiki") or {}
            curated = wiki.get("curated")
            if curated:
                curated_html = render_markdown_safe(curated.get("body_md") or "")
            groups = pack.get("groups") or []
            graph_records = pack.get("graph_records") or []
            work_items = pack.get("work_items") or []
            episodes = pack.get("episodes") or []
            related_skills = pack.get("skills") or []
            related_playbooks = pack.get("playbooks") or []
        except Exception as exc:
            log.warning("entity_hub_failed", error=str(exc))
            note = f"Entity hub unavailable: {exc}"
        ctx.update(
            {
                "slug": slug,
                "subject": subject,
                "entity": entity,
                "groups": groups,
                "note": note,
                "curated_html": curated_html,
                "curated_version": curated.get("version") if curated else None,
                "curated_updated": _dt(curated.get("updated_at")) if curated else "",
                "graph_records": graph_records,
                "work_items": work_items,
                "episodes": episodes,
                "related_skills": related_skills,
                "related_playbooks": related_playbooks,
            }
        )
        return _TEMPLATES.TemplateResponse(request, "entity_hub.html", ctx)

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
        # Playbooks now live in their own top-level, editable section. Keep this
        # path as a permanent redirect for bookmarks and the old wiki tab link.
        return RedirectResponse("/app/playbooks", status_code=308)

    # --- playbooks (skill collections) --------------------------------

    def _prefill_skill_names(
        request: Request,
        playbook: dict[str, Any] | None,
    ) -> list[str]:
        """Initial skill order for the playbook editor (saved or query prefill)."""
        if playbook and playbook.get("skill_names"):
            return list(playbook["skill_names"])
        names: list[str] = []
        for part in str(request.query_params.get("skills") or "").split(","):
            part = part.strip()
            if part and part not in names:
                names.append(part)
        single = str(request.query_params.get("skill") or "").strip()
        if single and single not in names:
            names.insert(0, single)
        return names

    async def _skill_options(principal: Principal) -> list[dict[str, Any]]:
        try:
            rows = await services.skills.list_skills(principal.org_id, limit=500)
            return [
                {"name": r["name"], "version": r["version"], "description": r.get("description")}
                for r in rows
            ]
        except Exception as exc:
            log.warning("skill_options_failed", error=str(exc))
            return []

    async def _playbook_skill_meta(
        principal: Principal, tool_recipe: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        meta: list[dict[str, Any]] = []
        for skill_name in skill_names_from_recipe(tool_recipe):
            skill = await services.skills.get_skill(principal.org_id, skill_name)
            meta.append({
                "name": skill_name,
                "version": skill.get("version") if skill else None,
                "description": skill.get("description") if skill else None,
                "available": skill is not None,
            })
        return meta

    async def playbooks_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "playbooks")
        playbooks: list[dict[str, Any]] = []
        note = ""
        try:
            procs = await services.procedural.list_procedures(
                principal.org_id, limit=200
            )
            for p in procs:
                tool_recipe = p.get("tool_recipe") or {}
                skill_names = skill_names_from_recipe(tool_recipe)
                skills = await _playbook_skill_meta(principal, tool_recipe)
                intro = (p.get("steps_md") or "").strip()
                playbooks.append({
                    "name": p["name"], "version": p["version"],
                    "description": p.get("description"), "tags": p.get("tags") or [],
                    "author": p.get("created_by"),
                    "updated": _dt(p.get("created_at")),
                    "skill_names": skill_names,
                    "skills": skills,
                    "intro_md": intro,
                    "intro_html": render_markdown_safe(intro) if intro else "",
                    "legacy_only": not skill_names and bool(intro),
                    "max_iterations": (tool_recipe.get("loop") or {}).get("max_iterations"),
                    "search": " ".join(
                        filter(None, [
                            p["name"], p.get("description") or "",
                            " ".join(p.get("tags") or []),
                            " ".join(skill_names), intro,
                        ])
                    ).lower(),
                })
        except Exception as exc:
            log.warning("playbooks_page_failed", error=str(exc))
            note = f"Playbooks unavailable: {exc}"
        flash = request.query_params.get("flash") or ""
        ctx.update({"playbooks": playbooks, "note": note, "flash": flash})
        return _TEMPLATES.TemplateResponse(request, "playbooks.html", ctx)

    async def playbook_new(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "playbooks")
        ctx.update({
            "playbook": None, "is_new": True, "note": "",
            "all_skills": await _skill_options(principal),
            "prefill_skill_names": _prefill_skill_names(request, None),
        })
        return _TEMPLATES.TemplateResponse(request, "playbook_edit.html", ctx)

    async def playbook_edit(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "playbooks")
        name = str(request.path_params["name"])
        playbook: dict[str, Any] | None = None
        note = ""
        try:
            row = await services.procedural.get_procedure(principal.org_id, name)
            if row is None:
                note = "Playbook not found."
            else:
                tool_recipe = row.get("tool_recipe") or {}
                playbook = {
                    **row,
                    "skill_names": skill_names_from_recipe(tool_recipe),
                    "skills": await _playbook_skill_meta(principal, tool_recipe),
                    "max_iterations": (tool_recipe.get("loop") or {}).get("max_iterations"),
                }
        except Exception as exc:
            log.warning("playbook_edit_failed", error=str(exc))
            note = f"Playbook unavailable: {exc}"
        ctx.update({
            "playbook": playbook, "is_new": False, "note": note,
            "all_skills": await _skill_options(principal),
            "prefill_skill_names": _prefill_skill_names(request, playbook),
        })
        return _TEMPLATES.TemplateResponse(request, "playbook_edit.html", ctx)

    async def playbook_save(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        name = str(form.get("name") or "").strip()
        intro_md = str(form.get("intro_md") or "").strip()
        description = str(form.get("description") or "").strip() or None
        tags = [t.strip() for t in str(form.get("tags") or "").split(",") if t.strip()]
        skills_raw = str(form.get("skills") or "").strip()
        skill_names = [line.strip() for line in skills_raw.splitlines() if line.strip()]
        max_iter_raw = str(form.get("max_iterations") or "").strip()
        max_iterations: int | None = int(max_iter_raw) if max_iter_raw.isdigit() else None
        if not name or not skill_names:
            return RedirectResponse("/app/playbooks?flash=invalid", status_code=303)
        try:
            tool_recipe = build_skill_recipe(skill_names, max_iterations=max_iterations)
            await services.ingestion().ingest_procedure(
                _ctx(principal),
                name=name,
                steps_md=intro_md,
                description=description,
                tool_recipe=tool_recipe,
                tags=tags or None,
                agent=principal.attribution,
                source="agent",
            )
        except ValueError:
            return RedirectResponse("/app/playbooks?flash=invalid", status_code=303)
        except Exception as exc:
            log.warning("playbook_save_failed", error=str(exc))
            return RedirectResponse("/app/playbooks?flash=error", status_code=303)
        return RedirectResponse("/app/playbooks?flash=saved", status_code=303)

    # --- skills (editable atomic instruction blocks) --------------------

    async def skills_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "skills")
        skills: list[dict[str, Any]] = []
        note = ""
        page_size = 10
        try:
            page = max(1, int(request.query_params.get("page") or "1"))
        except ValueError:
            page = 1
        q = (request.query_params.get("q") or "").strip()
        total = 0
        total_pages = 1
        try:
            total = await services.skills.count_skills(
                principal.org_id, query=q or None
            )
            total_pages = max(1, (total + page_size - 1) // page_size)
            if page > total_pages:
                page = total_pages
            offset = (page - 1) * page_size
            rows = await services.skills.list_skills(
                principal.org_id,
                query=q or None,
                limit=page_size,
                offset=offset,
            )
            skills = [
                {
                    "name": s["name"], "version": s["version"],
                    "description": s.get("description"), "tags": s.get("tags") or [],
                    "author": s.get("created_by"),
                    "updated": _dt(s.get("created_at")),
                    "body_html": render_markdown_safe(s.get("body_md") or ""),
                    "search": " ".join(
                        filter(None, [
                            s["name"], s.get("description") or "",
                            " ".join(s.get("tags") or []), s.get("body_md") or "",
                        ])
                    ).lower(),
                }
                for s in rows
            ]
        except Exception as exc:
            log.warning("skills_page_failed", error=str(exc))
            note = f"Skills unavailable: {exc}"
        flash = request.query_params.get("flash") or ""
        ctx.update({
            "skills": skills,
            "note": note,
            "flash": flash,
            "q": q,
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
        })
        return _TEMPLATES.TemplateResponse(request, "skills.html", ctx)

    async def skill_new(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "skills")
        ctx.update({"skill": None, "is_new": True, "note": ""})
        return _TEMPLATES.TemplateResponse(request, "skill_edit.html", ctx)

    async def skill_edit(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "skills")
        name = str(request.path_params["name"])
        skill: dict[str, Any] | None = None
        note = ""
        try:
            skill = await services.skills.get_skill(principal.org_id, name)
            if skill is None:
                note = "Skill not found."
        except Exception as exc:
            log.warning("skill_edit_failed", error=str(exc))
            note = f"Skill unavailable: {exc}"
        ctx.update({"skill": skill, "is_new": False, "note": note})
        return _TEMPLATES.TemplateResponse(request, "skill_edit.html", ctx)

    async def skill_save(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        name = str(form.get("name") or "").strip()
        body_md = str(form.get("body_md") or "").strip()
        description = str(form.get("description") or "").strip() or None
        tags = [t.strip() for t in str(form.get("tags") or "").split(",") if t.strip()]
        tool_hints_raw = str(form.get("tool_hints") or "").strip()
        tool_hints: dict[str, Any] | None = None
        if tool_hints_raw:
            try:
                parsed = json.loads(tool_hints_raw)
            except json.JSONDecodeError:
                return RedirectResponse("/app/skills?flash=invalid", status_code=303)
            if not isinstance(parsed, dict):
                return RedirectResponse("/app/skills?flash=invalid", status_code=303)
            tool_hints = parsed
        if not name or not body_md:
            return RedirectResponse("/app/skills?flash=invalid", status_code=303)
        try:
            await services.ingestion().ingest_skill(
                _ctx(principal),
                name=name,
                body_md=body_md,
                description=description,
                tags=tags or None,
                tool_hints=tool_hints,
                agent=principal.attribution,
                source="agent",
            )
        except Exception as exc:
            log.warning("skill_save_failed", error=str(exc))
            return RedirectResponse("/app/skills?flash=error", status_code=303)
        return RedirectResponse("/app/skills?flash=saved", status_code=303)

    # --- work (org task queue) ------------------------------------------

    async def _work_assignee_options(principal: Principal) -> list[dict[str, str]]:
        members: list[dict[str, str]] = []
        try:
            for m in await services.admin.list_members(_ctx(principal)):
                members.append({
                    "id": str(m.get("user_id")),
                    "email": m.get("email") or "",
                    "name": m.get("name") or m.get("email") or "",
                })
        except Exception as exc:
            log.warning("work_assignee_options_failed", error=str(exc))
        return members

    async def _work_link_options(
        principal: Principal, *, exclude_id: str | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Projects (for the project picker) and candidate parent tasks."""
        projects: list[dict[str, Any]] = []
        parents: list[dict[str, Any]] = []
        try:
            pdata = await get_state().facade.project_list(
                principal, team_id=None, initiative_id=None,
                include_archived=False, limit=100,
            )
            projects = pdata.get("projects") or []
        except Exception as exc:
            log.warning("work_link_projects_failed", error=str(exc))
        try:
            wdata = await get_state().facade.work_list(
                principal, work_status=None, assignee=None, mine=False,
                initiative_id=None, exclude_closed=True,
                sort="updated_at", sort_dir="desc", limit=100,
            )
            for it in wdata.get("items") or []:
                # Only top-level tasks can be parents, and never self.
                if it.get("parent_id"):
                    continue
                if exclude_id and str(it.get("id")) == exclude_id:
                    continue
                parents.append({"id": str(it.get("id")), "title": it.get("title") or ""})
        except Exception as exc:
            log.warning("work_link_parents_failed", error=str(exc))
        return projects, parents

    async def _work_item_projects(
        principal: Principal, work_id: str
    ) -> list[dict[str, Any]]:
        try:
            rows = await services.work.list_item_projects(principal.org_id, UUID(work_id))
            return [
                {"id": str(r.get("project_id")), "name": r.get("project_name") or ""}
                for r in rows
            ]
        except Exception as exc:
            log.warning("work_item_projects_failed", error=str(exc))
            return []

    async def _sync_work_project(
        principal: Principal, work_id: str, project_id: str | None
    ) -> None:
        """Make the task's project membership match the single selected project.

        The console models one project per task: drop any other links and add
        the chosen one (a no-op upsert when it already exists).
        """
        try:
            current = await services.work.list_item_projects(
                principal.org_id, UUID(work_id),
            )
            current_ids = {str(r.get("project_id")) for r in current}
            for pid in current_ids:
                if pid != project_id:
                    await get_state().facade.work_remove_from_project(
                        principal, work_id=work_id, project_id=pid,
                    )
            if project_id and project_id not in current_ids:
                await get_state().facade.work_add_to_project(
                    principal, work_id=work_id, project_id=project_id,
                    section_id=None, agent_override=None,
                )
        except Exception as exc:
            log.warning("work_project_sync_failed", error=str(exc))

    async def work_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "work")
        view = str(request.query_params.get("view") or "all")
        status_filter = str(request.query_params.get("status") or "").strip() or None
        sort = str(request.query_params.get("sort") or "updated_at").strip()
        sort_dir = str(request.query_params.get("dir") or "desc").strip()
        include_done = request.query_params.get("include_done") == "1"
        project_filter = str(request.query_params.get("project") or "").strip() or None
        items: list[dict[str, Any]] = []
        projects: list[dict[str, Any]] = []
        project_name = ""
        note = ""
        flash = request.query_params.get("flash") or ""
        try:
            work_status = status_filter
            mine = view == "mine"
            if view == "blocked":
                work_status = "blocked"
            data = await get_state().facade.work_list(
                principal,
                work_status=work_status,
                assignee=None,
                mine=mine,
                initiative_id=None,
                exclude_closed=not include_done and work_status is None,
                sort=sort,
                sort_dir=sort_dir,
                limit=100,
                project_id=project_filter,
            )
            items = _nest_subtasks(data.get("items") or [])
            try:
                pdata = await get_state().facade.project_list(
                    principal, team_id=None, initiative_id=None,
                    include_archived=False, limit=100,
                )
                projects = pdata.get("projects") or []
            except Exception as exc:
                log.warning("work_page_projects_failed", error=str(exc))
            if project_filter:
                match = next(
                    (p for p in projects if str(p.get("id")) == project_filter), None,
                )
                project_name = str(match.get("name") or "") if match else ""
        except Exception as exc:
            log.warning("work_page_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        ctx.update({
            "items": items, "view": view, "note": note, "flash": flash,
            "status_filter": status_filter or "",
            "sort": sort, "sort_dir": sort_dir,
            "include_done": include_done,
            "projects": projects,
            "project_filter": project_filter or "",
            "project_name": project_name,
        })
        return _TEMPLATES.TemplateResponse(request, "work.html", ctx)

    async def work_new(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "work")
        members = await _work_assignee_options(principal)
        projects, parent_options = await _work_link_options(principal, exclude_id=None)
        ctx.update({
            "item": None, "is_new": True, "note": "",
            "members": members,
            "projects": projects, "parent_options": parent_options,
        })
        return _TEMPLATES.TemplateResponse(request, "work_edit.html", ctx)

    async def work_detail(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "work")
        work_id = str(request.path_params["work_id"])
        item: dict[str, Any] | None = None
        comments: list[dict[str, Any]] = []
        note = ""
        try:
            item = await get_state().facade.work_get(principal, work_id=work_id)
            if item is None:
                note = "Work item not found."
            else:
                thread = await get_state().facade.work_comment_list(
                    principal, work_id=work_id, limit=100,
                )
                comments = thread.get("comments") or []
                item["projects"] = await _work_item_projects(principal, work_id)
                subs = await get_state().facade.work_subtasks_list(
                    principal, work_id=work_id,
                )
                item["subtasks"] = subs.get("subtasks") or []
                if item.get("parent_id"):
                    parent = await get_state().facade.work_get(
                        principal, work_id=str(item["parent_id"]),
                    )
                    item["parent"] = (
                        {"id": str(parent["id"]), "title": parent.get("title")}
                        if parent else None
                    )
        except Exception as exc:
            log.warning("work_detail_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        ctx.update({
            "item": item, "comments": comments, "note": note,
            "flash": request.query_params.get("flash") or "",
        })
        return _TEMPLATES.TemplateResponse(request, "work_detail.html", ctx)

    async def work_edit(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "work")
        work_id = str(request.path_params["work_id"])
        item: dict[str, Any] | None = None
        note = ""
        members = await _work_assignee_options(principal)
        projects, parent_options = await _work_link_options(principal, exclude_id=work_id)
        try:
            item = await get_state().facade.work_get(principal, work_id=work_id)
            if item is None:
                note = "Work item not found."
            else:
                item["projects"] = await _work_item_projects(principal, work_id)
        except Exception as exc:
            log.warning("work_edit_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        ctx.update({
            "item": item, "is_new": False, "note": note,
            "members": members,
            "projects": projects, "parent_options": parent_options,
            "flash": request.query_params.get("flash") or "",
        })
        return _TEMPLATES.TemplateResponse(request, "work_edit.html", ctx)

    async def work_comment(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        work_id = str(request.path_params["work_id"])
        body = str(form.get("body") or "").strip()
        if not body:
            return RedirectResponse(f"/app/work/{work_id}?flash=invalid", status_code=303)
        try:
            await get_state().facade.work_comment_add(
                principal, work_id=work_id, body=body, agent_override=None,
            )
            return RedirectResponse(f"/app/work/{work_id}?flash=commented", status_code=303)
        except Exception as exc:
            log.warning("work_comment_failed", error=str(exc))
            return RedirectResponse(f"/app/work/{work_id}?flash=error", status_code=303)

    async def work_save(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        title = str(form.get("title") or "").strip()
        if not title:
            return RedirectResponse("/app/work?flash=invalid", status_code=303)
        work_id = str(form.get("work_id") or "").strip()
        description_md = str(form.get("description_md") or "").strip() or None
        work_status = str(form.get("work_status") or "todo").strip()
        priority = str(form.get("priority") or "normal").strip()
        blocked_reason = str(form.get("blocked_reason") or "").strip() or None
        initiative_id = str(form.get("initiative_id") or "").strip() or None
        assignee_kind = str(form.get("assignee_kind") or "").strip()
        assignee_ref = str(form.get("assignee_ref") or "").strip()
        project_id = str(form.get("project_id") or "").strip() or None
        parent_id = str(form.get("parent_id") or "").strip()
        assignee_type: str | None = None
        assignee_email: str | None = None
        if assignee_kind == "user" and assignee_ref:
            assignee_type = "user"
            assignee_email = assignee_ref
        try:
            if work_id:
                updated = await get_state().facade.work_update(
                    principal,
                    work_id=work_id,
                    title=title,
                    description_md=description_md,
                    tags=None,
                    work_status=work_status,
                    priority=priority,
                    blocked_reason=blocked_reason,
                    assignee_type=assignee_type,
                    assignee_id=None,
                    assignee_email=assignee_email,
                    initiative_id=initiative_id,
                    due_at=None,
                    repo=None,
                    github=None,
                    agent_override=None,
                    parent_id=parent_id,
                )
                if updated is None:
                    return RedirectResponse("/app/work?flash=error", status_code=303)
                await _sync_work_project(principal, work_id, project_id)
                return RedirectResponse(f"/app/work/{work_id}?flash=saved", status_code=303)
            created = await get_state().facade.work_create(
                principal,
                title=title,
                description_md=description_md,
                tags=None,
                work_status=work_status,
                priority=priority,
                assignee_type=assignee_type,
                assignee_id=None,
                assignee_email=assignee_email,
                initiative_id=initiative_id,
                due_at=None,
                repo=None,
                github=None,
                agent_override=None,
                project_id=project_id,
                parent_id=parent_id or None,
            )
            new_id = created.get("id")
            return RedirectResponse(
                f"/app/work/{new_id}?flash=created" if new_id else "/app/work?flash=created",
                status_code=303,
            )
        except Exception as exc:
            log.warning("work_save_failed", error=str(exc))
            return RedirectResponse("/app/work?flash=error", status_code=303)

    # --- projects -------------------------------------------------------

    async def projects_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "projects")
        include_archived = request.query_params.get("include_archived") == "1"
        projects: list[dict[str, Any]] = []
        note = ""
        try:
            data = await get_state().facade.project_list(
                principal,
                team_id=None,
                initiative_id=None,
                include_archived=include_archived,
                limit=100,
            )
            projects = data.get("projects") or []
        except Exception as exc:
            log.warning("projects_page_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        ctx.update({
            "projects": projects,
            "include_archived": include_archived,
            "note": note,
            "flash": request.query_params.get("flash") or "",
        })
        return _TEMPLATES.TemplateResponse(request, "projects.html", ctx)

    async def project_create_post(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        name = str(form.get("name") or "").strip()
        if not name:
            return RedirectResponse("/app/projects?flash=invalid", status_code=303)
        description_md = str(form.get("description_md") or "").strip() or None
        default_view = str(form.get("default_view") or "board").strip()
        try:
            created = await get_state().facade.project_create(
                principal,
                name=name,
                description_md=description_md,
                team_id=None,
                default_view=default_view,
                color=None,
                owner_email=None,
                initiative_id=None,
                agent_override=None,
            )
            pid = created.get("id")
            return RedirectResponse(
                f"/app/projects/{pid}?flash=created" if pid else "/app/projects?flash=created",
                status_code=303,
            )
        except Exception as exc:
            log.warning("project_create_failed", error=str(exc))
            return RedirectResponse("/app/projects?flash=error", status_code=303)

    async def project_board(request: Request) -> Response:
        # Projects are now a label/grouping over tasks; a project's tasks live on
        # the Work page filtered to that project rather than a per-project board.
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        project_id = str(request.path_params["project_id"])
        return RedirectResponse(f"/app/work?project={project_id}", status_code=303)

    async def project_section_add_post(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        project_id = str(request.path_params["project_id"])
        name = str(form.get("name") or "").strip()
        if not name:
            return RedirectResponse(f"/app/projects/{project_id}?flash=invalid", status_code=303)
        try:
            await get_state().facade.project_section_add(
                principal, project_id=project_id, name=name,
            )
            return RedirectResponse(f"/app/projects/{project_id}?flash=section", status_code=303)
        except Exception as exc:
            log.warning("project_section_add_failed", error=str(exc))
            return RedirectResponse(f"/app/projects/{project_id}?flash=error", status_code=303)

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
            {
                "members": members,
                "bindings": bindings,
                "note": note,
                "flash": request.query_params.get("flash") or "",
                "roles": ["org_admin", "member", "viewer"],
                "member_roles": ["org_owner", "org_admin", "member", "viewer"],
            }
        )
        return _TEMPLATES.TemplateResponse(request, "people.html", ctx)

    async def people_grant(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        pid = str(form.get("principal_id") or "").strip()
        role_name = str(form.get("role_name") or "").strip()
        try:
            await services.admin.grant_role(
                _ctx(principal), principal_type="user",
                principal_id=UUID(pid), role_name=role_name,
            )
        except Exception as exc:
            log.warning("people_grant_failed", error=str(exc))
            return RedirectResponse("/app/people?flash=error", status_code=303)
        return RedirectResponse("/app/people?flash=saved", status_code=303)

    async def people_revoke(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
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
            return RedirectResponse("/app/people?flash=error", status_code=303)
        return RedirectResponse("/app/people?flash=revoked", status_code=303)

    async def people_add(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        email = str(form.get("email") or "").strip().lower()
        role = str(form.get("role") or "member").strip() or "member"
        if not email:
            return RedirectResponse("/app/people?flash=invalid", status_code=303)
        try:
            await services.admin.add_member(_ctx(principal), email=email, role=role)
        except Exception as exc:
            log.warning("people_add_failed", error=str(exc))
            return RedirectResponse("/app/people?flash=error", status_code=303)
        return RedirectResponse("/app/people?flash=added", status_code=303)

    # --- organizations (org switcher + self-service create) --------------

    async def orgs_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "orgs")
        ctx["flash"] = request.query_params.get("flash") or ""
        return _TEMPLATES.TemplateResponse(request, "orgs.html", ctx)

    async def org_create(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        if not principal.display:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        name = str(form.get("name") or "").strip()
        resp = RedirectResponse("/app", status_code=303)
        if not name:
            return RedirectResponse("/app/orgs?flash=invalid", status_code=303)
        try:
            slug = f"{slugify(name) or 'org'}-{secrets.token_hex(3)}"
            result = await signup_org(
                repo=services.tenancy, api_keys=services.api_keys, roles=services.roles,
                accounts=services.accounts, org_slug=slug, org_name=name,
                owner_email=principal.display,
            )
            await _issue_session_cookie(
                request,
                resp,
                org_id=result.org_id,
                user_id=result.owner_user_id,
                email=principal.display,
                account_id=principal.account_id,
            )
        except Exception as exc:
            log.warning("org_create_failed", error=str(exc))
            return RedirectResponse("/app/orgs?flash=error", status_code=303)
        return resp

    async def org_switch(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        email = principal.display
        if not email:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
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
        await _issue_session_cookie(
            request,
            resp,
            org_id=UUID(str(match["org_id"])),
            user_id=UUID(str(match["user_id"])),
            email=email,
            account_id=principal.account_id,
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
        try:
            keys = _key_rows(await services.api_keys.list_keys(principal.org_id))
        except Exception as exc:
            log.warning("keys_page_failed", error=str(exc))
            note = note or f"Unavailable: {exc}"
        ctx.update(
            {
                "keys": keys,
                "new_token": new_token,
                "note": note,
                "flash": request.query_params.get("flash") or "",
                "install_url": canonical_install_script_url(),
            }
        )
        return _TEMPLATES.TemplateResponse(request, "keys.html", ctx)

    async def key_mint(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        name = str(form.get("name") or "").strip() or "api-key"
        label = str(form.get("label") or "").strip() or name
        new_token = ""
        note = ""
        try:
            ctx = _ctx(principal)
            # Self-service: any read/write member (not view-only) can mint an
            # org-bound key. The free-text label drives memory attribution.
            await ctx.authorizer.require(principal, Permissions.MEMORY_CREATE)
            await services.roles.bind_role(
                org_id=principal.org_id,
                principal_type="agent",
                principal_id=principal.org_id,
                role_name="agent",
            )
            minted = await services.api_keys.mint(
                org_id=principal.org_id, principal_type="agent",
                principal_id=principal.org_id, name=name, label=label,
                created_by=principal.id,
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
        _, deny = await _verified_form(request)
        if deny:
            return deny
        try:
            ctx = _ctx(principal)
            await ctx.authorizer.require(principal, Permissions.ORG_ADMIN)
            await services.api_keys.revoke(
                principal.org_id, UUID(str(request.path_params["key_id"]))
            )
        except Exception as exc:
            log.warning("key_revoke_failed", error=str(exc))
            return RedirectResponse("/app/keys?flash=error", status_code=303)
        return RedirectResponse("/app/keys?flash=revoked", status_code=303)

    # --- strategy -------------------------------------------------------

    async def strategy_home(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "strategy")
        note = request.query_params.get("flash") or ""
        vision = mission = purpose = None
        plans: list[dict[str, Any]] = []
        active_tree: dict[str, Any] | None = None
        try:
            store = services.strategic
            vision = await store.get_active_statement(principal.org_id, "vision")
            mission = await store.get_active_statement(principal.org_id, "mission")
            purpose = await store.get_active_statement(principal.org_id, "purpose")
            plans = await store.list_plans(principal.org_id, active_only=True, limit=10)
            if plans:
                active_tree = await store.get_plan_tree(principal.org_id, plans[0]["id"])
        except Exception as exc:
            log.warning("strategy_home_failed", error=str(exc))
            note = f"Strategy unavailable: {exc}"
        ctx.update({
            "vision": vision,
            "mission": mission,
            "purpose": purpose,
            "plans": plans,
            "active_tree": active_tree,
            "note": note,
        })
        return _TEMPLATES.TemplateResponse(request, "strategy.html", ctx)

    async def strategy_statement_propose(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        kind = str(form.get("kind") or "").strip()
        content_md = str(form.get("content_md") or "").strip()
        if kind not in {"vision", "mission", "purpose"} or not content_md:
            return RedirectResponse("/app/strategy?flash=invalid", status_code=303)
        try:
            ctx = _ctx(principal)
            await ctx.authorizer.require(principal, Permissions.MEMORY_CREATE)
            await services.ingestion().ingest_strategic_statement(
                ctx, kind=kind, content_md=content_md, agent=principal.attribution,
            )
        except Exception as exc:
            log.warning("strategy_statement_propose_failed", error=str(exc))
            return RedirectResponse("/app/strategy?flash=error", status_code=303)
        return RedirectResponse("/app/strategy?flash=saved", status_code=303)

    async def strategy_plan_detail(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "strategy")
        plan_id = UUID(str(request.path_params["plan_id"]))
        tree: dict[str, Any] | None = None
        note = ""
        try:
            tree = await services.strategic.get_plan_tree(principal.org_id, plan_id)
            if tree is None:
                note = "Plan not found."
        except Exception as exc:
            log.warning("strategy_plan_detail_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        ctx.update({"tree": tree, "note": note})
        return _TEMPLATES.TemplateResponse(request, "strategy_plan.html", ctx)

    async def ontology_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "ontology")
        note = ""
        schema: dict[str, Any] = {}
        entities: list[dict[str, Any]] = []
        action_log: list[dict[str, Any]] = []
        try:
            data = await get_state().facade.ontology_admin_view(principal)
            schema = data.get("schema") or {}
            entities = data.get("entities") or []
            action_log = [
                {
                    "id": e.get("id"),
                    "action": e.get("action_type"),
                    "status": e.get("status"),
                    "actor": e.get("actor") or "\u2014",
                    "created": _dt(e.get("created_at")),
                }
                for e in (data.get("action_log") or [])
            ]
        except Exception as exc:
            log.warning("ontology_page_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        ctx.update({
            "note": note,
            "link_types": schema.get("link_types") or [],
            "object_kinds": schema.get("object_kinds") or [],
            "interfaces": schema.get("interfaces") or [],
            "action_types": schema.get("action_types") or [],
            "entities": entities,
            "action_log": action_log,
        })
        return _TEMPLATES.TemplateResponse(request, "ontology.html", ctx)

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
            subtitle="RBAC-gated writes and reads — every permission change is logged.",
            headers=["When", "Agent", "Action", "Resource", "Target"], rows=rows, note=note,
        )

    # --- consent (removed 2026-06-19) — capture is now gated only by
    #     settings.capture_enabled; no per-agent consent grants. ---------

    async def connections_page(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        ctx = await _shell(request, principal, "connections")
        connections: list[dict[str, Any]] = []
        note = ""
        try:
            rctx = _ctx(principal)
            connections = await services.connectors.list_connectors(rctx)
        except Exception as exc:
            log.warning("connections_page_failed", error=str(exc))
            note = f"Unavailable: {exc}"
        flash = request.query_params.get("status") or request.query_params.get("flash") or ""
        kind = request.query_params.get("kind") or ""
        reason = request.query_params.get("reason") or ""
        ctx.update({
            "connections": connections,
            "note": note,
            "flash": flash,
            "kind": kind,
            "reason": reason,
            "gmail_configured": bool(
                services.settings.gmail_client_id
                and services.settings.gmail_client_secret
                and services.settings.gmail_redirect_uri
            ),
            "slack_configured": bool(
                services.settings.slack_client_id
                and services.settings.slack_client_secret
                and services.settings.slack_redirect_uri
            ),
            "discord_configured": bool(
                services.settings.discord_client_id
                and services.settings.discord_client_secret
                and services.settings.discord_redirect_uri
                and services.settings.discord_bot_token
            ),
        })
        return _TEMPLATES.TemplateResponse(request, "connections.html", ctx)

    async def connections_sync(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        connector_id = str(request.path_params["connector_id"])
        try:
            rctx = _ctx(principal)
            await services.connectors.sync(rctx, UUID(connector_id))
        except Exception as exc:
            log.warning("connections_sync_failed", error=str(exc))
            return RedirectResponse("/app/connections?status=error", status_code=303)
        return RedirectResponse("/app/connections?status=synced", status_code=303)

    async def connections_disconnect(request: Request) -> Response:
        principal = _session(request)
        if principal is None:
            return _redirect_login()
        form, deny = await _verified_form(request)
        if deny:
            return deny
        connector_id = str(request.path_params["connector_id"])
        try:
            rctx = _ctx(principal)
            await services.connectors.delete(rctx, UUID(connector_id))
        except Exception as exc:
            log.warning("connections_disconnect_failed", error=str(exc))
            return RedirectResponse("/app/connections?status=error", status_code=303)
        return RedirectResponse("/app/connections?status=disconnected", status_code=303)

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
        Route("/app/wiki/topic/{slug}/edit", wiki_edit, methods=["GET"]),
        Route("/app/wiki/topic/{slug}/edit", wiki_edit_save, methods=["POST"]),
        Route("/app/wiki/entity/{slug}", entity_hub, methods=["GET"]),
        Route("/app/entity/{slug}", entity_hub, methods=["GET"]),
        Route("/app/playbooks", playbooks_page, methods=["GET"]),
        Route("/app/playbooks/new", playbook_new, methods=["GET"]),
        Route("/app/playbooks/save", playbook_save, methods=["POST"]),
        Route("/app/playbooks/{name}", playbook_edit, methods=["GET"]),
        Route("/app/skills", skills_page, methods=["GET"]),
        Route("/app/skills/new", skill_new, methods=["GET"]),
        Route("/app/skills/save", skill_save, methods=["POST"]),
        Route("/app/skills/{name}", skill_edit, methods=["GET"]),
        Route("/app/work", work_page, methods=["GET"]),
        Route("/app/work/new", work_new, methods=["GET"]),
        Route("/app/work/save", work_save, methods=["POST"]),
        Route("/app/work/{work_id}", work_detail, methods=["GET"]),
        Route("/app/work/{work_id}/edit", work_edit, methods=["GET"]),
        Route("/app/work/{work_id}/comment", work_comment, methods=["POST"]),
        Route("/app/projects", projects_page, methods=["GET"]),
        Route("/app/projects/create", project_create_post, methods=["POST"]),
        Route("/app/projects/{project_id}", project_board, methods=["GET"]),
        Route("/app/projects/{project_id}/sections", project_section_add_post, methods=["POST"]),
        Route("/app/strategy", strategy_home, methods=["GET"]),
        Route("/app/strategy/statement", strategy_statement_propose, methods=["POST"]),
        Route("/app/strategy/plans/{plan_id}", strategy_plan_detail, methods=["GET"]),
        Route("/app/memory", memory_explorer, methods=["GET"]),
        Route("/app/memory/{memory_id}", memory_detail, methods=["GET"]),
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
        Route("/app/ontology", ontology_page, methods=["GET"]),
        Route("/app/audit", audit_page, methods=["GET"]),
        Route("/app/settings", settings_page, methods=["GET"]),
        Route("/app/settings/export", settings_export, methods=["GET"]),
        Route("/app/settings/purge", settings_purge, methods=["POST"]),
        Route("/app/connections", connections_page, methods=["GET"]),
        Route("/app/connections/{connector_id}/sync", connections_sync, methods=["POST"]),
        Route("/app/connections/{connector_id}/disconnect", connections_disconnect, methods=["POST"]),
    ]
    for path, (active, title) in _PLACEHOLDERS.items():
        routes.append(Route(path, _placeholder(active, title), methods=["GET"]))
    return routes
