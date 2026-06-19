"""The ``/v1`` REST application: orgs, teams, projects, identities, memory, admin.

Every handler builds a :class:`RequestContext` from the authenticated principal
and delegates to the service layer, so tenant isolation (RLS), permission
checks, and audit happen uniformly. Connector routes are attached by
``teamshared.connectors`` when a connector service is provided.
"""

from __future__ import annotations

import secrets
from typing import Any
from uuid import UUID

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from teamshared.admin.exceptions import ErasureNotConfirmedError
from teamshared.identity.provisioning import signup_org
from teamshared.identity.rbac import Permissions
from teamshared.memory.request_context import RequestContext
from teamshared.memory.types import TimeRange
from teamshared.server.api.errors import ApiError, error_response, map_exception
from teamshared.server.api.middleware import (
    IdempotencyMiddleware,
    PrincipalAuthMiddleware,
    RateLimitMiddleware,
)
from teamshared.server.rate_limit import enforce_admin_export, enforce_admin_purge
from teamshared.server.services import ProductionServices

_PUBLIC = frozenset({"/v1/healthz", "/v1/orgs"})


def _ctx(request: Request, services: ProductionServices) -> RequestContext:
    principal = request.state.principal
    return RequestContext(
        principal=principal,
        db=services.tenant_db,
        authorizer=services.authorizer(),
        request_id=getattr(request.state, "request_id", ""),
    )


async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as exc:
        raise ApiError(400, "invalid_json", "request body must be valid JSON") from exc
    if not isinstance(body, dict):
        raise ApiError(400, "invalid_json", "request body must be a JSON object")
    return body


def _limit(request: Request, default: int = 20, maximum: int = 200) -> int:
    raw = request.query_params.get("limit")
    if raw is None:
        return default
    try:
        return max(1, min(maximum, int(raw)))
    except ValueError:
        return default


def build_api_app(
    services: ProductionServices,
    *,
    admin_secret: str | None = None,
    session_secret: str | None = None,
) -> Starlette:
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "api": "v1"})

    async def create_org(request: Request) -> JSONResponse:
        supplied = request.headers.get("x-teamshared-admin-secret", "")
        if not admin_secret or not secrets.compare_digest(supplied, admin_secret):
            return error_response(request, 403, "forbidden", "admin secret required")
        body = await _json(request)
        slug = body.get("org_slug")
        name = body.get("org_name")
        email = body.get("owner_email")
        if not (isinstance(slug, str) and slug and isinstance(name, str) and name
                and isinstance(email, str) and email):
            raise ApiError(400, "bad_request", "org_slug, org_name, owner_email are required")
        result = await signup_org(
            repo=services.tenancy, api_keys=services.api_keys, roles=services.roles,
            accounts=services.accounts,
            org_slug=slug, org_name=name, owner_email=email,
        )
        return JSONResponse(
            {
                "org_id": str(result.org_id),
                "owner_user_id": str(result.owner_user_id),
                "api_key": {"prefix": result.api_key.prefix, "token": result.api_key.token},
            },
            status_code=201,
        )

    async def org_me(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        org = await services.tenancy.get_organization(ctx.org_id)
        if org is None:
            raise ApiError(404, "not_found", "org not found")
        return JSONResponse(org.model_dump(mode="json"))

    async def create_team(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        body = await _json(request)
        team = await services.tenancy.create_team(ctx.org_id, body["slug"], body["name"])
        return JSONResponse(team.model_dump(mode="json"), status_code=201)

    async def list_teams(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_READ)
        teams = await services.tenancy.list_teams(ctx.org_id)
        return JSONResponse({"teams": [t.model_dump(mode="json") for t in teams]})

    async def create_project(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        body = await _json(request)
        team_id = body.get("team_id")
        proj = await services.tenancy.create_project(
            ctx.org_id, body["slug"], body["name"], UUID(team_id) if team_id else None
        )
        return JSONResponse(proj.model_dump(mode="json"), status_code=201)

    async def list_projects(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        await ctx.authorizer.require(ctx.principal, Permissions.MEMORY_READ)
        projs = await services.tenancy.list_projects(ctx.org_id)
        return JSONResponse({"projects": [p.model_dump(mode="json") for p in projs]})

    async def create_api_key(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        body = await _json(request)
        ptype = body.get("principal_type", "agent")
        pid = body.get("principal_id")
        key = await services.api_keys.mint(
            org_id=ctx.org_id,
            principal_type=ptype,
            principal_id=UUID(pid) if pid else ctx.principal.id,
            name=body.get("name", "api-key"),
            scopes=body.get("scopes"),
            created_by=ctx.principal.id,
        )
        return JSONResponse(
            {"id": str(key.id), "prefix": key.prefix, "token": key.token}, status_code=201
        )

    async def list_api_keys(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        keys = await services.api_keys.list_keys(ctx.org_id)
        return JSONResponse({"api_keys": keys})

    async def revoke_api_key(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        await ctx.authorizer.require(ctx.principal, Permissions.ORG_ADMIN)
        ok = await services.api_keys.revoke(ctx.org_id, UUID(request.path_params["key_id"]))
        return JSONResponse({"revoked": ok})

    async def ingest_memory(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        body = await _json(request)
        content = body.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ApiError(400, "bad_request", "content is required")
        scope_ref = body.get("scope_ref_id")
        result = await services.ingestion().ingest(
            ctx, content,
            kind=body.get("kind", "note"),
            scope=body.get("scope", "org"),
            scope_ref_id=UUID(scope_ref) if scope_ref else None,
            visibility=body.get("visibility", "private"),
            subject=body.get("subject"),
            tags=body.get("tags"),
            source=body.get("source", "manual"),
            confidence=body.get("confidence"),
            importance=body.get("importance"),
            require_approval=bool(body.get("require_approval", False)),
        )
        return JSONResponse(
            {
                "memory_id": str(result.memory_id) if result.memory_id else None,
                "status": result.status,
                "deduped_of": str(result.deduped_of) if result.deduped_of else None,
                "pii": [f.kind for f in result.pii],
                "injection_risk": result.injection.risk if result.injection else 0.0,
            },
            status_code=201,
        )

    async def search_memory(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        body = await _json(request)
        query = body.get("query")
        if not isinstance(query, str) or not query:
            raise ApiError(400, "bad_request", "query is required")
        tr = None
        if isinstance(body.get("time_range"), dict):
            tr = TimeRange(**body["time_range"])
        scopes = body.get("scope") or [
            "semantic", "episodic", "procedural", "skill", "strategic", "work",
        ]
        result = await services.retrieval().search(
            ctx, query, scopes=scopes, k=int(body.get("k", 8)), time_range=tr
        )
        return JSONResponse(result.model_dump(mode="json"))

    async def get_memory(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        item = await services.memory_service.get(ctx, UUID(request.path_params["memory_id"]))
        if item is None:
            raise ApiError(404, "not_found", "memory not found")
        return JSONResponse(item.model_dump(mode="json"))

    async def patch_memory(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        body = await _json(request)
        ok = await services.memory_service.update(
            ctx, UUID(request.path_params["memory_id"]), body["content"]
        )
        return JSONResponse({"updated": ok})

    async def delete_memory(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        ok = await services.memory_service.delete(ctx, UUID(request.path_params["memory_id"]))
        return JSONResponse({"deleted": ok})

    async def share_memory(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        body = await _json(request)
        target_id = body.get("target_id")
        ok = await services.memory_service.share(
            ctx, UUID(request.path_params["memory_id"]),
            target_scope=body.get("target_scope", "org"),
            target_id=UUID(target_id) if target_id else None,
        )
        return JSONResponse({"shared": ok})

    async def list_audit(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        await ctx.authorizer.require(ctx.principal, Permissions.AUDIT_READ)
        events = await services.audit.list_events(
            ctx.org_id, action=request.query_params.get("action"), limit=_limit(request, 100)
        )
        return JSONResponse({"events": events})

    async def list_connectors(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        items = await services.connectors.list_connectors(ctx)
        return JSONResponse({"connectors": items})

    async def create_connector(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        body = await _json(request)
        cid = await services.connectors.create(
            ctx, kind=body["kind"], name=body.get("name", body["kind"]),
            config=body.get("config", {}),
        )
        token = body.get("token")
        if isinstance(token, str) and token:
            await services.connectors.store_token(ctx, cid, token)
        return JSONResponse({"id": str(cid)}, status_code=201)

    async def sync_connector(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        report = await services.connectors.sync(ctx, UUID(request.path_params["connector_id"]))
        return JSONResponse(
            {"connector_id": str(report.connector_id), "fetched": report.fetched,
             "imported": report.imported, "next_cursor": report.next_cursor}
        )

    async def delete_connector(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        ok = await services.connectors.delete(ctx, UUID(request.path_params["connector_id"]))
        return JSONResponse({"deleted": ok})

    async def list_members(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        return JSONResponse({"members": await services.admin.list_members(ctx)})

    async def grant_role(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        body = await _json(request)
        ok = await services.admin.grant_role(
            ctx, principal_type=body.get("principal_type", "user"),
            principal_id=UUID(request.path_params["user_id"]), role_name=body["role"],
        )
        return JSONResponse({"granted": ok})

    async def list_roles(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        return JSONResponse({"bindings": await services.admin.list_role_bindings(ctx)})

    async def create_agent(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        body = await _json(request)
        aid = await services.admin.create_agent(
            ctx, name=body["name"], kind=body.get("kind", "agent"),
            runtime=body.get("runtime", "user"),
        )
        return JSONResponse({"id": str(aid)}, status_code=201)

    async def list_agents(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        return JSONResponse({"agents": await services.admin.list_agents(ctx)})

    async def create_retention(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        body = await _json(request)
        rid = await services.admin.create_retention_policy(
            ctx, name=body["name"], max_age_days=body.get("max_age_days"),
            max_items=body.get("max_items"), kinds=body.get("kinds"),
        )
        return JSONResponse({"id": str(rid)}, status_code=201)

    async def list_retention(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        return JSONResponse({"policies": await services.admin.list_retention_policies(ctx)})

    async def export_org(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is not None:
            blocked = await enforce_admin_export(limiter, ctx.principal)
            if blocked is not None:
                return blocked
        payload = await services.admin.export_memory(ctx)
        return JSONResponse(
            payload,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="teamshared-export-{ctx.org_id}.json"'
                ),
            },
        )

    async def purge_user(request: Request) -> JSONResponse:
        ctx = _ctx(request, services)
        limiter = getattr(request.app.state, "rate_limiter", None)
        if limiter is not None:
            blocked = await enforce_admin_purge(limiter, ctx.principal)
            if blocked is not None:
                return blocked
        confirmed = request.headers.get("x-confirm-erasure", "").strip() == "1"
        if not confirmed:
            try:
                body = await request.json()
            except Exception:
                body = {}
            if isinstance(body, dict):
                confirmed = body.get("confirm") is True
        if not confirmed:
            raise ErasureNotConfirmedError()
        deleted = await services.admin.purge_user_memory(
            ctx, UUID(request.path_params["user_id"])
        )
        return JSONResponse({"soft_deleted": deleted})

    routes = [
        Route("/v1/healthz", healthz, methods=["GET"]),
        Route("/v1/orgs", create_org, methods=["POST"]),
        Route("/v1/orgs/me", org_me, methods=["GET"]),
        Route("/v1/teams", create_team, methods=["POST"]),
        Route("/v1/teams", list_teams, methods=["GET"]),
        Route("/v1/projects", create_project, methods=["POST"]),
        Route("/v1/projects", list_projects, methods=["GET"]),
        Route("/v1/api-keys", create_api_key, methods=["POST"]),
        Route("/v1/api-keys", list_api_keys, methods=["GET"]),
        Route("/v1/api-keys/{key_id}", revoke_api_key, methods=["DELETE"]),
        Route("/v1/memory", ingest_memory, methods=["POST"]),
        Route("/v1/memory/search", search_memory, methods=["POST"]),
        Route("/v1/memory/{memory_id}", get_memory, methods=["GET"]),
        Route("/v1/memory/{memory_id}", patch_memory, methods=["PATCH"]),
        Route("/v1/memory/{memory_id}", delete_memory, methods=["DELETE"]),
        Route("/v1/memory/{memory_id}/share", share_memory, methods=["POST"]),
        Route("/v1/audit", list_audit, methods=["GET"]),
        Route("/v1/connectors", list_connectors, methods=["GET"]),
        Route("/v1/connectors", create_connector, methods=["POST"]),
        Route("/v1/connectors/{connector_id}/sync", sync_connector, methods=["POST"]),
        Route("/v1/connectors/{connector_id}", delete_connector, methods=["DELETE"]),
        Route("/v1/members", list_members, methods=["GET"]),
        Route("/v1/members/{user_id}/roles", grant_role, methods=["POST"]),
        Route("/v1/roles", list_roles, methods=["GET"]),
        Route("/v1/agents", create_agent, methods=["POST"]),
        Route("/v1/agents", list_agents, methods=["GET"]),
        Route("/v1/retention-policies", create_retention, methods=["POST"]),
        Route("/v1/retention-policies", list_retention, methods=["GET"]),
        Route("/v1/admin/export", export_org, methods=["GET"]),
        Route("/v1/admin/users/{user_id}/memory", purge_user, methods=["DELETE"]),
    ]

    middleware = [
        Middleware(
            PrincipalAuthMiddleware,
            api_keys=services.api_keys,
            session_secret=session_secret,
            public_paths=_PUBLIC,
        ),
        Middleware(RateLimitMiddleware),
        Middleware(IdempotencyMiddleware),
    ]

    api = Starlette(routes=routes, middleware=middleware)

    async def on_error(request: Request, exc: Exception) -> JSONResponse:
        return map_exception(request, exc)

    api.add_exception_handler(Exception, on_error)
    return api
