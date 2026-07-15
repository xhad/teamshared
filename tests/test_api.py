"""REST API: auth/rate-limit middleware (unit) + end-to-end (integration)."""

from __future__ import annotations

import uuid

import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from teamshared.config import get_settings
from teamshared.server.api.middleware import PrincipalAuthMiddleware, RateLimitMiddleware


class _StubKeys:
    def __init__(self, principal: object | None) -> None:
        self._principal = principal

    async def authenticate(self, token: str) -> object | None:
        return self._principal if token == "good" else None


def _protected_app(keys: object) -> Starlette:
    async def whoami(request: Request) -> JSONResponse:
        p = request.state.principal
        return JSONResponse({"org": str(p.org_id)})

    return Starlette(
        routes=[Route("/v1/x", whoami, methods=["GET"])],
        middleware=[Middleware(PrincipalAuthMiddleware, api_keys=keys)],
    )


def test_auth_rejects_missing_token() -> None:
    app = _protected_app(_StubKeys(None))
    with TestClient(app) as client:
        resp = client.get("/v1/x")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "missing_bearer_token"


def test_auth_rejects_bad_token() -> None:
    app = _protected_app(_StubKeys(None))
    with TestClient(app) as client:
        resp = client.get("/v1/x", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "invalid_token"


def test_rate_limit_trips() -> None:
    from teamshared.identity.principal import Principal

    principal = Principal(org_id=uuid.uuid4(), type="user", id=uuid.uuid4())

    async def whoami(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    app = Starlette(
        routes=[Route("/v1/x", whoami, methods=["GET"])],
        middleware=[
            Middleware(PrincipalAuthMiddleware, api_keys=_StubKeys(principal)),
            Middleware(RateLimitMiddleware, limit=3, window_seconds=60),
        ],
    )
    with TestClient(app) as client:
        codes = [
            client.get("/v1/x", headers={"Authorization": "Bearer good"}).status_code
            for _ in range(5)
        ]
    assert codes.count(200) == 3
    assert codes.count(429) == 2


@pytest.mark.integration
async def test_end_to_end_signup_ingest_search() -> None:
    import httpx

    from teamshared.server.api import build_api_app
    from teamshared.server.services import build_services

    settings = get_settings()
    services = await build_services(settings)
    api = build_api_app(services, admin_secret="test-admin")
    # Mount at /v1 like production so route paths (defined without the /v1
    # prefix inside the api sub-app) resolve correctly.
    from starlette.applications import Starlette
    from starlette.routing import Mount

    mounted = Starlette(routes=[Mount("/v1", app=api)])
    # Drive the ASGI app in *this* event loop (not the sync TestClient, which
    # runs on a separate loop/thread and would strand the async pool created by
    # build_services, deadlocking on connection checkout).
    transport = httpx.ASGITransport(app=mounted)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            slug = f"e2e-{uuid.uuid4().hex[:8]}"
            resp = await client.post(
                "/v1/orgs",
                headers={"X-Teamshared-Admin-Secret": "test-admin"},
                json={"org_slug": slug, "org_name": "E2E", "owner_email": "o@e2e.test"},
            )
            assert resp.status_code == 201
            token = resp.json()["api_key"]["token"]
            org_id = uuid.UUID(resp.json()["org_id"])
            auth = {"Authorization": f"Bearer {token}"}

            resp = await client.post(
                "/v1/memory", headers=auth,
                json={"content": "the staging db is reset every night at 2am", "scope": "org"},
            )
            assert resp.status_code == 201
            assert resp.json()["status"] == "active"

            resp = await client.post(
                "/v1/memory/search", headers=auth,
                json={"query": "when is staging reset", "scope": ["semantic"]},
            )
            assert resp.status_code == 200
            contents = [r["content"] for r in resp.json()["records"]]
            assert any("staging db is reset" in c for c in contents)

            # Production-path shared-brain smoke: one agent writes, another
            # recalls, and the audit rollup records a cross-agent result.
            agent_tokens: list[str] = []
            for label in ("cursor", "hermes"):
                minted = await client.post(
                    "/v1/api-keys",
                    headers=auth,
                    json={"name": label, "label": label, "principal_type": "agent"},
                )
                assert minted.status_code == 201
                agent_tokens.append(minted.json()["token"])

            marker = f"cross-agent-{uuid.uuid4().hex}"
            written = await client.post(
                "/v1/memory",
                headers={"Authorization": f"Bearer {agent_tokens[0]}"},
                json={"content": f"{marker} uses pgvector", "scope": "org"},
            )
            assert written.status_code == 201

            recalled = await client.post(
                "/v1/memory/search",
                headers={"Authorization": f"Bearer {agent_tokens[1]}"},
                json={"query": marker, "scope": ["semantic"]},
            )
            assert recalled.status_code == 200
            records = recalled.json()["records"]
            assert any(marker in record["content"] for record in records)
            assert any(record.get("agent") == "cursor" for record in records)

            metrics = await services.audit.recall_metrics(org_id)
            assert metrics["cross_agent_recalls"] >= 1
            assert metrics["active_agents"] >= 2
    finally:
        await services.tenant_db.close()
