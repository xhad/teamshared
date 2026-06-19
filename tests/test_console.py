"""Signed-in web console (`/app`) + one-time-passcode (OTP) auth.

Drives the real `register_console_routes` Starlette routes with a mocked
`ProductionServices` (its `working` is an in-memory OTP fake) and a fake
`ServerState`. Pins the auth flow (email -> OTP code -> session cookie -> home),
the unauthenticated redirect, the live-stats home render, and the sections.
"""

from __future__ import annotations

import re
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from teamshared.server import console as console_mod
from teamshared.server.console import register_console_routes
from teamshared.server.state import clear_state, set_state

DEFAULT_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
OWNER_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
SECRET = "test-session-secret"


class _Conn:
    def __init__(self, row: tuple | None) -> None:
        self._row = row

    async def execute(self, sql: str, params: object = None):
        cur = MagicMock()
        cur.fetchone = AsyncMock(return_value=self._row)
        cur.fetchall = AsyncMock(return_value=[])
        return cur


class _OrgCM:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _Conn:
        return self._conn

    async def __aexit__(self, *exc: object) -> bool:
        return False


class _FakeWorking:
    """In-memory stand-in for WorkingMemory's email-only sign-in OTP storage."""

    def __init__(self) -> None:
        self._otp: dict[str, str] = {}

    async def set_login_otp(
        self, email: str, code: str, *, ttl: int = 30, max_attempts: int = 5
    ) -> None:
        self._otp[email.strip().lower()] = code

    async def verify_login_otp(self, email: str, code: str) -> bool:
        key = email.strip().lower()
        if self._otp.get(key) == code:
            del self._otp[key]  # single-use
            return True
        return False


def _orgs(*orgs: tuple[uuid.UUID, uuid.UUID, str]) -> list[dict[str, object]]:
    """Build auth_account_orgs-shaped rows: (org_id, user_id, name)."""
    return [
        {"org_id": o, "user_id": u, "slug": n.lower().replace(" ", "-"),
         "name": n, "role": "org_owner"}
        for (o, u, n) in orgs
    ]


def _build(
    *,
    owner_row: tuple | None = (OWNER_ID,),
    consent: object | None = None,
    auth_disabled: bool = True,
    smtp: bool = False,
    orgs: list[dict[str, object]] | None = None,
):
    settings = SimpleNamespace(
        session_secret=SECRET,
        default_org_id=DEFAULT_ORG,
        auth_disabled=auth_disabled,  # dev mode: OTP code shown in the page
        console_session_ttl=2_592_000,
        public_url="http://testserver",
        otp_ttl_seconds=30,
        otp_max_attempts=5,
        smtp_host="smtp.test" if smtp else None,
        smtp_port=587,
        smtp_username=None,
        smtp_password=None,
        smtp_from="teamshared <no-reply@test>" if smtp else None,
        smtp_starttls=True,
    )
    tenant_db = MagicMock()
    tenant_db.org = MagicMock(return_value=_OrgCM(_Conn(owner_row)))
    services = MagicMock()
    services.tenant_db = tenant_db
    services.working = _FakeWorking()
    # The email belongs to one org (the default) unless a test overrides it.
    services.accounts.list_orgs = AsyncMock(
        return_value=orgs if orgs is not None else _orgs((DEFAULT_ORG, OWNER_ID, "teamshared"))
    )
    # Console write handlers enforce RBAC via ctx.authorizer.require; give the
    # fake services an authorizer whose require is awaitable (allow by default).
    services.authorizer = MagicMock(
        return_value=SimpleNamespace(
            require=AsyncMock(),
            has=AsyncMock(return_value=True),
        )
    )
    if consent is not None:
        services.consent = consent

    routes = register_console_routes(settings, services)
    app = Starlette(routes=routes)
    return TestClient(app, follow_redirects=False), services


def _fake_state() -> SimpleNamespace:
    return SimpleNamespace(
        settings=SimpleNamespace(default_org_id=DEFAULT_ORG),
        working=SimpleNamespace(stats=AsyncMock(return_value={"active": 2, "total": 3})),
        procedural=SimpleNamespace(
            stats=AsyncMock(return_value={"playbooks": 2, "versions": 5})
        ),
        services=SimpleNamespace(
            vector_store=SimpleNamespace(
                pillar_stats=AsyncMock(
                    return_value={"semantic": 5, "episodic": 2, "by_agent": {"cursor": 4, "hermes": 1}}
                )
            ),
            audit=SimpleNamespace(
                list_events=AsyncMock(
                    return_value=[
                        {"occurred_at": "2026-05-28T10:00:00", "agent": "cursor", "action": "memory.write"}
                    ]
                )
            ),
            strategic=SimpleNamespace(
                stats=AsyncMock(return_value={"plans": 1, "objectives": 2, "statements": 3})
            ),
            work=SimpleNamespace(
                stats=AsyncMock(return_value={"open": 4, "blocked": 1, "pending_approval": 2})
            ),
        ),
    )


@pytest.fixture
def state_with_stats(monkeypatch):
    monkeypatch.setattr(
        console_mod,
        "check_components",
        AsyncMock(return_value={"status": "ok", "components": {"redis": "ok", "postgres": "ok"}}),
    )
    set_state(_fake_state())
    try:
        yield
    finally:
        clear_state()


def _request_otp(client: TestClient, email: str = "owner@example.com") -> str:
    resp = client.post("/login", data={"email": email})
    assert resp.status_code == 200
    match = re.search(r'data-otp="(\d{6})"', resp.text)
    assert match, "dev login page should embed the OTP code"
    return match.group(1)


def _login(client: TestClient) -> None:
    code = _request_otp(client)
    verify = client.post("/login/verify", data={"email": "owner@example.com", "code": code})
    assert verify.status_code == 303
    assert verify.headers["location"] == "/app"
    assert "ts_session" in verify.cookies or any(
        "ts_session" in c for c in verify.headers.get_list("set-cookie")
    )


def _csrf_token(client: TestClient, page_path: str = "/app") -> str:
    resp = client.get(page_path)
    assert resp.status_code == 200
    match = re.search(
        r'<meta name="csrf-token" content="([^"]+)"'
        r'|name="csrf_token" value="([^"]+)"',
        resp.text,
    )
    assert match, f"csrf_token missing on {page_path}"
    return match.group(1) or match.group(2)


def _app_post(
    client: TestClient, path: str, data: dict[str, str] | None = None
):
    """POST to a console write route with a valid CSRF token."""
    payload = dict(data or {})
    payload["csrf_token"] = _csrf_token(client)
    return client.post(path, data=payload)


def test_unauthenticated_app_redirects_to_login() -> None:
    client, _ = _build()
    resp = client.get("/app")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_login_page_renders() -> None:
    client, _ = _build()
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "Your email" in resp.text


def test_login_post_shows_code_stage() -> None:
    client, _ = _build()
    resp = client.post("/login", data={"email": "owner@example.com"})
    assert resp.status_code == 200
    assert 'name="code"' in resp.text  # advanced to the code-entry stage


def test_any_email_gets_a_code_self_service() -> None:
    # Self-service: any email can request a code (it provisions on verify).
    client, _ = _build()
    resp = client.post("/login", data={"email": "brand-new@example.com"})
    assert resp.status_code == 200
    assert 'name="code"' in resp.text  # code-entry stage
    assert re.search(r'data-otp="\d{6}"', resp.text)  # dev mode shows the code


def test_otp_grants_session_and_renders_home(state_with_stats) -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/app")
    assert resp.status_code == 200
    assert "Team mind overview" in resp.text
    # Live stats rendered through the home template.
    assert "Working sessions" in resp.text
    assert "cursor" in resp.text


def test_console_shows_app_version_beside_brand(state_with_stats) -> None:
    from teamshared import __version__

    client, _ = _build()
    _login(client)
    resp = client.get("/app")
    assert resp.status_code == 200
    assert f"v{__version__}" in resp.text
    # The version badge links to the health endpoint.
    assert 'class="ver" href="/health"' in resp.text


def test_invalid_otp_is_rejected() -> None:
    client, _ = _build()
    _request_otp(client)
    resp = client.post(
        "/login/verify", data={"email": "owner@example.com", "code": "000000"}
    )
    assert resp.status_code == 401
    assert "invalid or expired" in resp.text


def test_otp_emailed_in_prod_and_not_shown(monkeypatch) -> None:
    client, _ = _build(auth_disabled=False, smtp=True)
    sent = AsyncMock()
    monkeypatch.setattr(console_mod.mailer, "send_login_code", sent)
    resp = client.post("/login", data={"email": "owner@example.com"})
    assert resp.status_code == 200
    assert 'name="code"' in resp.text  # advanced to code stage
    assert "data-otp=" not in resp.text  # code is NOT shown on the page in prod
    sent.assert_awaited_once()
    # send_login_code(settings, email, code, ttl)
    assert sent.await_args.args[1] == "owner@example.com"
    assert re.fullmatch(r"\d{6}", sent.await_args.args[2])


def test_otp_email_failure_does_not_leak(monkeypatch) -> None:
    client, _ = _build(auth_disabled=False, smtp=True)
    monkeypatch.setattr(
        console_mod.mailer, "send_login_code", AsyncMock(side_effect=RuntimeError("smtp down"))
    )
    resp = client.post("/login", data={"email": "owner@example.com"})
    # Same neutral code screen even when delivery fails (no enumeration / no 500).
    assert resp.status_code == 200
    assert 'name="code"' in resp.text
    assert "data-otp=" not in resp.text


def test_otp_is_single_use(state_with_stats) -> None:
    client, _ = _build()
    code = _request_otp(client)
    first = client.post("/login/verify", data={"email": "owner@example.com", "code": code})
    assert first.status_code == 303
    # Re-submitting the consumed code fails.
    second = client.post("/login/verify", data={"email": "owner@example.com", "code": code})
    assert second.status_code == 401


def test_logout_clears_cookie() -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/logout")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_settings_renders_system_health_when_authed(state_with_stats) -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/app/settings")
    assert resp.status_code == 200
    assert "System status" in resp.text
    assert "redis: ok" in resp.text
    assert "later build phase" not in resp.text


def test_settings_shows_export_when_permitted(state_with_stats) -> None:
    client, services = _build()
    services.authorizer.return_value.has = AsyncMock(return_value=True)
    services.admin.export_max_items = 50_000
    services.admin.list_members_for_erasure = AsyncMock(
        return_value=[{"user_id": str(OWNER_ID), "email": "owner@example.com",
                       "display_name": None, "role": "org_owner", "status": "active"}]
    )
    _login(client)
    resp = client.get("/app/settings")
    assert resp.status_code == 200
    assert "Download org export" in resp.text
    assert "/app/settings/export" in resp.text


def test_settings_purge_requires_csrf(state_with_stats) -> None:
    client, services = _build()
    services.authorizer.return_value.has = AsyncMock(
        side_effect=lambda _p, perm: perm == "memory:admin"
    )
    _login(client)
    client.cookies.pop("ts_csrf", None)
    resp = client.post(
        "/app/settings/purge",
        data={"user_id": str(OWNER_ID), "confirm_erase": "yes"},
    )
    assert resp.status_code == 403
    services.admin.purge_user_memory.assert_not_called()


def test_home_does_not_render_component_health_badges(state_with_stats) -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/app")
    assert resp.status_code == 200
    assert "distiller:" not in resp.text
    assert "System status" in resp.text


def test_home_renders_work_stats(state_with_stats) -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/app")
    assert resp.status_code == 200
    assert "Open tasks" in resp.text
    assert ">4<" in resp.text
    assert "/app/work" in resp.text


def test_read_screen_redirects_when_unauthed() -> None:
    client, _ = _build()
    resp = client.get("/app/agents")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


# --------------------------------------------------------------------------- #
# Read screens (Phase 3)
# --------------------------------------------------------------------------- #
def test_memory_explorer_lists_recent() -> None:
    client, services = _build()
    services.vector_store.list_recent = AsyncMock(
        return_value=[
            SimpleNamespace(
                id="m1", content="Team host is teamshared.com", pillar="semantic",
                agent="cursor", kind="fact", created_at="2026-05-28T10:00:00",
            )
        ]
    )
    _login(client)
    resp = client.get("/app/memory")
    assert resp.status_code == 200
    assert "Memory explorer" in resp.text
    assert "teamshared.com" in resp.text
    assert '/app/memory/m1' in resp.text
    services.vector_store.list_recent.assert_awaited()


def test_memory_explorer_search_uses_keyword_search() -> None:
    client, services = _build()
    services.vector_store.keyword_search = AsyncMock(return_value=[])
    services.authorizer = MagicMock(return_value=MagicMock())
    _login(client)
    resp = client.get("/app/memory", params={"q": "postgres", "pillar": "semantic"})
    assert resp.status_code == 200
    services.vector_store.keyword_search.assert_awaited()


def test_memory_detail_renders_item() -> None:
    client, services = _build()
    services.vector_store.get = AsyncMock(
        return_value=SimpleNamespace(
            id="m1", content="hello world", pillar="semantic", kind="fact",
            subject="teamshared", tags=["infra"], scope="org", visibility="org",
            source="agent", confidence=0.9, status="active", version=1,
            created_at="2026-05-28T10:00:00",
        )
    )
    _login(client)
    resp = client.get("/app/memory/00000000-0000-0000-0000-0000000000aa")
    assert resp.status_code == 200
    assert "hello world" in resp.text
    assert "teamshared" in resp.text


def test_memory_detail_not_found_for_bad_id() -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/app/memory/not-a-uuid")
    assert resp.status_code == 200
    assert "Memory not found." in resp.text


def test_agents_page_lists_agents() -> None:
    client, services = _build()
    services.admin.list_agents = AsyncMock(
        return_value=[
            {"id": "a1", "name": "cursor", "kind": "agent", "status": "active",
             "created_at": "2026-05-12T00:00:00"}
        ]
    )
    _login(client)
    resp = client.get("/app/agents")
    assert resp.status_code == 200
    assert "Agents" in resp.text
    assert "cursor" in resp.text


def test_agents_page_lists_background_runs() -> None:
    client, services = _build()
    services.admin.list_agents = AsyncMock(return_value=[])
    run_svc = SimpleNamespace(
        list_runs=AsyncMock(
            return_value=[
                {
                    "id": "r1", "status": "completed", "agent_name": "cursor",
                    "work_title": "Ship it", "work_item_id": "w1",
                    "playbook_name": "ship-pr", "playbook_version": 2,
                    "model": "gpt-4o-mini", "provider": "openrouter", "error": None,
                    "created_at": "2026-05-28T10:00:00",
                    "started_at": "2026-05-28T10:00:01",
                    "completed_at": "2026-05-28T10:00:05",
                }
            ]
        ),
    )
    services.agent_run_service = MagicMock(return_value=run_svc)
    _login(client)
    resp = client.get("/app/agents")
    assert resp.status_code == 200
    assert "Background runs" in resp.text
    assert "ship-pr" in resp.text
    assert "/app/agents/runs/r1" in resp.text


def test_agent_run_detail_shows_trace_and_model_calls() -> None:
    client, services = _build()
    run_svc = SimpleNamespace(
        get_run=AsyncMock(
            return_value={
                "id": "r1", "status": "completed", "agent_name": "cursor",
                "work_title": "Ship it", "work_item_id": "w1",
                "playbook_name": "ship-pr", "playbook_version": 2,
                "model": "gpt-4o-mini", "provider": "openrouter", "error": None,
                "created_at": "2026-05-28T10:00:00",
                "started_at": "2026-05-28T10:00:01",
                "completed_at": "2026-05-28T10:00:05",
                "trace": [
                    {"event_type": "started", "summary": "began work",
                     "sequence": 0, "payload_json": {}, "created_at": "2026-05-28T10:00:01"}
                ],
                "model_calls": [
                    {"model": "gpt-4o-mini", "provider": "openrouter",
                     "request_id": "req-xyz", "prompt_tokens": 100,
                     "completion_tokens": 20, "latency_ms": 42, "error": None,
                     "created_at": "2026-05-28T10:00:03"}
                ],
            }
        ),
    )
    services.agent_run_service = MagicMock(return_value=run_svc)
    _login(client)
    resp = client.get(f"/app/agents/runs/{uuid.uuid4()}")
    assert resp.status_code == 200
    assert "Trace timeline" in resp.text
    assert "began work" in resp.text
    assert "Model calls" in resp.text
    assert "42" in resp.text  # latency_ms rendered in the model-calls table


def test_people_page_lists_members() -> None:
    client, services = _build()
    services.admin.list_members = AsyncMock(
        return_value=[
            {"user_id": "u1", "email": "owner@acme.ai", "display_name": "Owner",
             "role": "org_owner", "status": "active"}
        ]
    )
    services.admin.list_role_bindings = AsyncMock(return_value=[])
    _login(client)
    resp = client.get("/app/people")
    assert resp.status_code == 200
    assert "owner@acme.ai" in resp.text


def test_keys_page_lists_keys() -> None:
    client, services = _build()
    services.api_keys.list_keys = AsyncMock(
        return_value=[
            {"name": "CI", "prefix": "tsk_abc", "principal_type": "service",
             "principal_id": "s1", "created_at": "2026-05-10T00:00:00",
             "last_used_at": None, "revoked_at": None}
        ]
    )
    _login(client)
    resp = client.get("/app/keys")
    assert resp.status_code == 200
    assert "tsk_abc" in resp.text
    assert "active" in resp.text


def test_approvals_page_lists_pending() -> None:
    client, services = _build()
    services.approvals.list_pending = AsyncMock(
        return_value=[
            {"id": "ap1", "memory_id": "m1", "reason": "pii_detected",
             "created_at": "2026-05-28T10:00:00", "content": "sensitive note"},
            {"id": "ap2", "ontology_entity_id": "e1", "reason": "ontology_entity_proposed",
             "created_at": "2026-06-01T10:00:00", "content": "Acme (Project)"},
        ]
    )
    _login(client)
    resp = client.get("/app/approvals")
    assert resp.status_code == 200
    assert "pii_detected" in resp.text
    assert "ontology / entity" in resp.text


def test_ontology_page_renders() -> None:
    client, _services = _build()
    facade = MagicMock()
    facade.ontology_admin_view = AsyncMock(return_value={
        "schema": {
            "link_types": [{"name": "mentions", "from_kinds": [], "to_kinds": [], "cardinality": "many_to_many"}],
            "object_kinds": [{"name": "Person", "interfaces": [], "description": "human"}],
            "interfaces": [],
            "action_types": [{"name": "link_entities", "requires_approval": False}],
        },
        "entities": [{"slug": "alice", "name": "Alice", "kind": "Person", "status": "active", "created_by": "cursor"}],
        "action_log": [],
    })
    set_state(SimpleNamespace(facade=facade))
    _login(client)
    resp = client.get("/app/ontology")
    assert resp.status_code == 200
    assert "mentions" in resp.text
    assert "alice" in resp.text


def test_work_page_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    client, services = _build()
    facade = MagicMock()
    facade.work_list = AsyncMock(return_value={"count": 1, "items": [{
        "id": "w1", "title": "Ship work queue", "work_status": "todo",
        "priority": "normal", "assignee_type": "agent", "assignee_id": "a1",
        "assignee_label": "cursor", "initiative_title": None,
        "updated_at": "2026-06-07T12:00:00+00:00", "due_at": None,
    }]})
    set_state(SimpleNamespace(facade=facade))
    services.admin.list_agents = AsyncMock(return_value=[{"id": "a1", "name": "cursor"}])
    services.admin.list_members = AsyncMock(return_value=[{
        "user_id": "u1", "email": "owner@example.com", "name": "Owner",
    }])
    try:
        _login(client)
        resp = client.get("/app/work")
        assert resp.status_code == 200
        assert "Work" in resp.text
        assert "Ship work queue" in resp.text
        assert "cursor" in resp.text
        assert "/app/work/new" in resp.text
    finally:
        clear_state()


def test_work_new_renders_compose_form(monkeypatch: pytest.MonkeyPatch) -> None:
    client, services = _build()
    services.admin.list_agents = AsyncMock(return_value=[{"id": "a1", "name": "cursor"}])
    services.admin.list_members = AsyncMock(return_value=[{
        "user_id": "u1", "email": "owner@example.com", "name": "Owner",
    }])
    try:
        _login(client)
        resp = client.get("/app/work/new")
        assert resp.status_code == 200
        assert "work-compose-card" in resp.text
        assert "Write a task name" in resp.text
        assert "Create task" in resp.text
        assert "Description (markdown)" not in resp.text
    finally:
        clear_state()


def test_projects_page_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _services = _build()
    facade = MagicMock()
    facade.project_list = AsyncMock(return_value={"count": 1, "projects": [{
        "id": "p1", "name": "Q3 Launch", "description_md": "Ship it",
        "default_view": "board", "project_status": "active",
    }]})
    set_state(SimpleNamespace(facade=facade))
    try:
        _login(client)
        resp = client.get("/app/projects")
        assert resp.status_code == 200
        assert "Q3 Launch" in resp.text
        assert "/app/work?project=p1" in resp.text
        assert "Create project" in resp.text
    finally:
        clear_state()


def test_project_board_redirects_to_filtered_work(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _services = _build()
    set_state(SimpleNamespace(facade=MagicMock()))
    try:
        _login(client)
        resp = client.get("/app/projects/p1", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/app/work?project=p1"
    finally:
        clear_state()


def test_project_create_post(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _services = _build()
    facade = MagicMock()
    facade.project_list = AsyncMock(return_value={"count": 0, "projects": []})
    facade.project_create = AsyncMock(return_value={"id": "p9", "name": "New"})
    set_state(SimpleNamespace(facade=facade))
    try:
        _login(client)
        token = _csrf_token(client, "/app/projects")
        resp = client.post(
            "/app/projects/create",
            data={"name": "New", "default_view": "board", "csrf_token": token},
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/app/projects/p9?flash=created"
        facade.project_create.assert_awaited_once()
    finally:
        clear_state()


def test_work_detail_renders_comments(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _services = _build()
    facade = MagicMock()
    facade.work_get = AsyncMock(return_value={
        "id": "w1", "title": "Ship work queue", "work_status": "todo",
        "priority": "normal", "assignee_label": "cursor",
        "description_md": "MVP", "blocked_reason": None,
    })
    facade.work_comment_list = AsyncMock(return_value={
        "count": 1,
        "comments": [{
            "id": "c1", "body_md": "Started implementation",
            "author_label": "cursor", "created_at": "2026-06-07T12:00:00+00:00",
        }],
    })
    facade.work_subtasks_list = AsyncMock(return_value={"count": 0, "subtasks": []})
    set_state(SimpleNamespace(facade=facade))
    try:
        _login(client)
        resp = client.get("/app/work/w1")
        assert resp.status_code == 200
        assert "Started implementation" in resp.text
        assert "/app/work/w1/edit" in resp.text
    finally:
        clear_state()


def test_strategy_page_renders() -> None:
    client, services = _build()
    services.strategic = MagicMock()
    services.strategic.get_active_statement = AsyncMock(
        side_effect=lambda _org, kind: {
            "kind": kind,
            "content_md": f"Our {kind}",
            "version": 1,
            "created_by": "cursor",
        }
    )
    services.strategic.list_plans = AsyncMock(return_value=[])
    _login(client)
    resp = client.get("/app/strategy")
    assert resp.status_code == 200
    assert "Strategy" in resp.text
    assert "Our vision" in resp.text


def test_audit_page_lists_events() -> None:
    client, services = _build()
    services.audit.list_events = AsyncMock(
        return_value=[
            {"occurred_at": "2026-05-28T10:00:00", "agent": "cursor",
             "action": "memory.write", "resource_type": "memory", "target_id": "m1"}
        ]
    )
    _login(client)
    resp = client.get("/app/audit")
    assert resp.status_code == 200
    assert "memory.write" in resp.text


def test_read_screen_degrades_on_backend_error() -> None:
    client, services = _build()
    services.admin.list_agents = AsyncMock(side_effect=RuntimeError("db down"))
    _login(client)
    resp = client.get("/app/agents")
    assert resp.status_code == 200
    assert "Unavailable" in resp.text


# --------------------------------------------------------------------------- #
# Wiki (Phase 4)
# --------------------------------------------------------------------------- #
def test_wiki_redirects_when_unauthed() -> None:
    client, _ = _build()
    resp = client.get("/app/wiki")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_wiki_home_lists_topics_and_tags() -> None:
    client, services = _build()
    services.vector_store.list_subjects = AsyncMock(
        return_value=[{"subject": "teamshared infra", "count": 3,
                       "updated_at": "2026-05-28T10:00:00"}]
    )
    services.vector_store.pillar_stats = AsyncMock(
        return_value={"tags": [("infra", 3), ("postgres", 1)]}
    )
    services.vector_store.list_recent = AsyncMock(
        return_value=[
            SimpleNamespace(id="m1", content="prod host is teamshared.com", subject="teamshared infra",
                            agent="cursor", created_at="2026-05-28T10:00:00")
        ]
    )
    _login(client)
    resp = client.get("/app/wiki")
    assert resp.status_code == 200
    assert "Team wiki" in resp.text
    assert "teamshared infra" in resp.text
    assert "infra" in resp.text
    assert "/app/wiki/topic/teamshared-infra" in resp.text


def test_wiki_topic_groups_records_by_kind() -> None:
    client, services = _build()
    services.vector_store.list_subjects = AsyncMock(
        return_value=[{"subject": "teamshared infra", "count": 2,
                       "updated_at": "2026-05-28T10:00:00"}]
    )
    services.vector_store.list_by_subject = AsyncMock(
        return_value=[
            SimpleNamespace(id="m1", content="prod host is teamshared.com", kind="fact",
                            agent="cursor", tags=["infra"], created_at="2026-05-28T10:00:00"),
            SimpleNamespace(id="m2", content="prefer make over raw compose", kind="preference",
                            agent="hermes", tags=[], created_at="2026-05-27T10:00:00"),
        ]
    )
    services.wiki.get_page = AsyncMock(return_value=None)
    _login(client)
    resp = client.get("/app/wiki/topic/teamshared-infra")
    assert resp.status_code == 200
    assert "prod host is teamshared.com" in resp.text
    assert "fact" in resp.text
    assert "preference" in resp.text
    assert "Curated article" not in resp.text
    services.vector_store.list_by_subject.assert_awaited()


def test_wiki_topic_not_found_for_unknown_slug() -> None:
    client, services = _build()
    services.vector_store.list_subjects = AsyncMock(return_value=[])
    _login(client)
    resp = client.get("/app/wiki/topic/nope")
    assert resp.status_code == 200
    assert "Topic not found." in resp.text


def test_wiki_timeline_lists_episodes() -> None:
    client, services = _build()
    services.vector_store.list_episodes = AsyncMock(
        return_value=[
            SimpleNamespace(id="e1", content="migrated to pgvector", subject=None,
                            agent="cursor", created_at="2026-05-28T10:00:00")
        ]
    )
    _login(client)
    resp = client.get("/app/wiki/timeline")
    assert resp.status_code == 200
    assert "migrated to pgvector" in resp.text


def test_wiki_topic_prefers_curated_page() -> None:
    client, services = _build()
    services.vector_store.list_subjects = AsyncMock(
        return_value=[{"subject": "teamshared infra", "count": 2,
                       "updated_at": "2026-05-28T10:00:00"}]
    )
    services.vector_store.list_by_subject = AsyncMock(
        return_value=[
            SimpleNamespace(id="m1", content="prod host is teamshared.com", kind="fact",
                            agent="cursor", tags=["infra"], created_at="2026-05-28T10:00:00")
        ]
    )
    services.wiki.get_page = AsyncMock(
        return_value={"body_md": "# Infra\n\nProd runs on **Spark**.", "version": 3,
                      "updated_at": "2026-05-28T11:00:00"}
    )
    _login(client)
    resp = client.get("/app/wiki/topic/teamshared-infra")
    assert resp.status_code == 200
    assert "Curated article" in resp.text
    assert "<strong>Spark</strong>" in resp.text
    assert "Source records" in resp.text  # raw records still shown beneath
    assert "prod host is teamshared.com" in resp.text


def test_wiki_playbooks_redirects_to_dedicated_section() -> None:
    # The old Wiki tab now redirects to the editable top-level Playbooks section.
    client, _ = _build()
    _login(client)
    resp = client.get("/app/wiki/playbooks")
    assert resp.status_code == 308
    assert resp.headers["location"] == "/app/playbooks"


def test_entity_hub_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = _build()
    facade = MagicMock()
    facade.entity_view = AsyncMock(
        return_value={
            "slug": "teamshared",
            "subject": "teamshared",
            "note": "",
            "entity": {"kind": "Project", "name": "teamshared", "status": "active", "interfaces": []},
            "wiki": {"curated": None},
            "groups": [("fact", [{"content": "prod host is teamshared.com", "agent": "cursor", "tags": []}])],
            "graph_records": [],
            "work_items": [],
            "approvals": [],
            "episodes": [],
        }
    )
    set_state(SimpleNamespace(facade=facade))
    try:
        _login(client)
        resp = client.get("/app/wiki/entity/teamshared")
        assert resp.status_code == 200
        assert "teamshared" in resp.text
        assert "prod host is teamshared.com" in resp.text
        assert "Ontology entity" in resp.text
    finally:
        clear_state()


# --------------------------------------------------------------------------- #
# Playbooks section (editable procedural memory)
# --------------------------------------------------------------------------- #
def test_playbooks_page_lists_and_sanitizes() -> None:
    client, services = _build()
    services.procedural.list_procedures = AsyncMock(
        return_value=[
            {"name": "ship-pr", "version": 2, "description": "How to ship",
             "tags": ["git"], "created_by": "cursor",
             "created_at": "2026-05-28T10:00:00",
             "steps_md": "# Steps\n\n1. do **thing**\n\n<script>alert(1)</script>"}
        ]
    )
    _login(client)
    resp = client.get("/app/playbooks")
    assert resp.status_code == 200
    assert "ship-pr" in resp.text
    assert "<strong>thing</strong>" in resp.text
    assert "<script>alert(1)</script>" not in resp.text
    assert "/app/playbooks/ship-pr" in resp.text  # edit link
    assert "/app/playbooks/new" in resp.text  # create button
    assert 'id="pb-filter"' in resp.text  # live search bar
    assert 'data-search="' in resp.text  # filterable card metadata


def test_playbook_new_form_renders() -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/app/playbooks/new")
    assert resp.status_code == 200
    assert 'name="steps_md"' in resp.text
    assert 'name="name"' in resp.text


def test_playbook_edit_form_prefills() -> None:
    client, services = _build()
    services.procedural.get_procedure = AsyncMock(
        return_value={"name": "ship-pr", "version": 3, "description": "How to ship",
                      "tags": ["git", "release"],
                      "steps_md": "# Steps\n\n1. do thing"}
    )
    _login(client)
    resp = client.get("/app/playbooks/ship-pr")
    assert resp.status_code == 200
    assert "ship-pr" in resp.text
    assert "1. do thing" in resp.text
    assert "git, release" in resp.text  # tags joined into the input


def test_playbook_save_creates_version_and_redirects() -> None:
    client, services = _build()
    services.ingestion.return_value.ingest_procedure = AsyncMock(
        return_value=SimpleNamespace(status="active")
    )
    _login(client)
    resp = _app_post(
        client, "/app/playbooks/save",
        {"name": "ship-pr", "description": "How to ship",
         "tags": "git, release", "steps_md": "# Steps\n\n1. do thing"},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/playbooks?flash=saved"
    services.ingestion.return_value.ingest_procedure.assert_awaited_once()
    kwargs = services.ingestion.return_value.ingest_procedure.await_args.kwargs
    assert kwargs["name"] == "ship-pr"
    assert kwargs["steps_md"] == "# Steps\n\n1. do thing"
    assert kwargs["tags"] == ["git", "release"]


def test_playbook_save_requires_name_and_steps() -> None:
    client, services = _build()
    services.ingestion.return_value.ingest_procedure = AsyncMock()
    _login(client)
    resp = _app_post(client, "/app/playbooks/save", {"name": "", "steps_md": ""})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/playbooks?flash=invalid"
    services.ingestion.return_value.ingest_procedure.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Skills section (editable atomic instruction blocks)
# --------------------------------------------------------------------------- #
def test_skills_page_lists_and_sanitizes() -> None:
    client, services = _build()
    services.skills.list_skills = AsyncMock(
        return_value=[
            {"name": "ship-pr", "version": 2, "description": "How to ship",
             "tags": ["git"], "created_by": "cursor",
             "created_at": "2026-05-28T10:00:00",
             "body_md": "# Ship\n\n1. do **thing**\n\n<script>alert(1)</script>"}
        ]
    )
    _login(client)
    resp = client.get("/app/skills")
    assert resp.status_code == 200
    assert "ship-pr" in resp.text
    assert "<strong>thing</strong>" in resp.text
    assert "<script>alert(1)</script>" not in resp.text
    assert "/app/skills/ship-pr" in resp.text
    assert "/app/skills/new" in resp.text
    assert 'id="sk-filter"' in resp.text


def test_skill_new_form_renders() -> None:
    client, _ = _build()
    _login(client)
    resp = client.get("/app/skills/new")
    assert resp.status_code == 200
    assert 'name="body_md"' in resp.text
    assert 'name="name"' in resp.text


def test_skill_edit_form_prefills() -> None:
    client, services = _build()
    services.skills.get_skill = AsyncMock(
        return_value={"name": "ship-pr", "version": 3, "description": "How to ship",
                      "tags": ["git", "release"],
                      "body_md": "# Ship\n\n1. do thing",
                      "tool_hints": {"prefer": ["memory_recall"]}}
    )
    _login(client)
    resp = client.get("/app/skills/ship-pr")
    assert resp.status_code == 200
    assert "ship-pr" in resp.text
    assert "1. do thing" in resp.text
    assert "git, release" in resp.text
    assert "memory_recall" in resp.text


def test_skill_save_creates_version_and_redirects() -> None:
    client, services = _build()
    services.ingestion.return_value.ingest_skill = AsyncMock(
        return_value=SimpleNamespace(status="active")
    )
    _login(client)
    resp = _app_post(
        client, "/app/skills/save",
        {"name": "ship-pr", "description": "How to ship",
         "tags": "git, release", "body_md": "# Ship\n\n1. do thing",
         "tool_hints": '{"prefer": ["work_list"]}'},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/skills?flash=saved"
    services.ingestion.return_value.ingest_skill.assert_awaited_once()
    kwargs = services.ingestion.return_value.ingest_skill.await_args.kwargs
    assert kwargs["name"] == "ship-pr"
    assert kwargs["body_md"] == "# Ship\n\n1. do thing"
    assert kwargs["tags"] == ["git", "release"]
    assert kwargs["tool_hints"] == {"prefer": ["work_list"]}


def test_skill_save_requires_name_and_body() -> None:
    client, services = _build()
    services.ingestion.return_value.ingest_skill = AsyncMock()
    _login(client)
    resp = _app_post(client, "/app/skills/save", {"name": "", "body_md": ""})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/skills?flash=invalid"
    services.ingestion.return_value.ingest_skill.assert_not_awaited()


def test_skill_save_rejects_invalid_tool_hints() -> None:
    client, services = _build()
    services.ingestion.return_value.ingest_skill = AsyncMock()
    _login(client)
    resp = _app_post(
        client, "/app/skills/save",
        {"name": "x", "body_md": "body", "tool_hints": "not-json"},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/skills?flash=invalid"
    services.ingestion.return_value.ingest_skill.assert_not_awaited()


# --------------------------------------------------------------------------- #
# Write actions (Phase 5)
# --------------------------------------------------------------------------- #
def test_write_action_redirects_when_unauthed() -> None:
    client, _ = _build()
    resp = client.post("/app/agents/add", data={"name": "ralph"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_agent_add_creates_and_redirects() -> None:
    client, services = _build()
    services.admin.create_agent = AsyncMock(return_value=uuid.uuid4())
    _login(client)
    resp = _app_post(client, "/app/agents/add", {"name": "ralph"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/agents"
    services.admin.create_agent.assert_awaited_once()
    assert services.admin.create_agent.await_args.kwargs["name"] == "ralph"


def test_agent_disable_redirects() -> None:
    client, services = _build()
    services.admin.set_agent_status = AsyncMock(return_value=True)
    aid = str(uuid.uuid4())
    _login(client)
    resp = _app_post(client, f"/app/agents/{aid}/status", {"status": "disabled"})
    assert resp.status_code == 303
    services.admin.set_agent_status.assert_awaited_once()
    assert services.admin.set_agent_status.await_args.args[2] == "disabled"


def test_key_mint_shows_token_once() -> None:
    client, services = _build()
    services.api_keys.list_keys = AsyncMock(return_value=[])
    services.admin.list_agents = AsyncMock(return_value=[])
    services.api_keys.mint = AsyncMock(
        return_value=SimpleNamespace(id=uuid.uuid4(), prefix="tsk_abc", token="tsk_abc_secret")
    )
    _login(client)
    resp = _app_post(
        client, "/app/keys/mint",
        {"agent_id": str(uuid.uuid4()), "name": "CI"},
    )
    assert resp.status_code == 200
    assert "tsk_abc_secret" in resp.text  # shown once on the page, not via redirect
    services.api_keys.mint.assert_awaited_once()
    # Minting is self-service: gated on memory:create (members), not org:admin.
    perms_required = {
        call.args[1] for call in services.authorizer().require.await_args_list
    }
    assert "memory:create" in perms_required
    assert "org:admin" not in perms_required


def test_key_revoke_redirects() -> None:
    client, services = _build()
    services.api_keys.revoke = AsyncMock(return_value=True)
    kid = str(uuid.uuid4())
    _login(client)
    resp = _app_post(client, f"/app/keys/{kid}/revoke")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/keys"
    services.api_keys.revoke.assert_awaited_once()


def test_approval_approve_redirects_and_decides() -> None:
    client, services = _build()
    services.approvals.decide = AsyncMock(return_value=uuid.uuid4())
    services.audit.record = AsyncMock()
    aid = str(uuid.uuid4())
    _login(client)
    resp = _app_post(client, f"/app/approvals/{aid}/decide", {"decision": "approve"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/approvals"
    services.approvals.decide.assert_awaited_once()
    assert services.approvals.decide.await_args.kwargs["approved"] is True


def test_people_grant_and_revoke_redirect() -> None:
    client, services = _build()
    services.admin.grant_role = AsyncMock(return_value=True)
    services.admin.revoke_role = AsyncMock(return_value=True)
    _login(client)
    uid = str(uuid.uuid4())
    grant = _app_post(
        client, "/app/people/grant", {"principal_id": uid, "role_name": "member"}
    )
    assert grant.status_code == 303
    services.admin.grant_role.assert_awaited_once()
    revoke = _app_post(
        client,
        "/app/people/revoke",
        {"principal_type": "user", "principal_id": uid, "role_name": "member"},
    )
    assert revoke.status_code == 303
    services.admin.revoke_role.assert_awaited_once()


# --------------------------------------------------------------------------- #
# Multi-tenant: self-service orgs, switcher, add-member
# --------------------------------------------------------------------------- #
def test_login_auto_signs_up_own_org_when_no_orgs(monkeypatch) -> None:
    new_org = uuid.uuid4()
    new_user = uuid.uuid4()
    signup = AsyncMock(
        return_value=SimpleNamespace(
            org_id=new_org, owner_user_id=new_user,
            api_key=SimpleNamespace(prefix="tsk_x", token="tsk_x_y"),
        )
    )
    monkeypatch.setattr(console_mod, "signup_org", signup)
    client, _ = _build(orgs=[])  # email belongs to no org yet
    resp = client.post("/login", data={"email": "fresh@example.com"})
    code = re.search(r'data-otp="(\d{6})"', resp.text).group(1)
    verify = client.post(
        "/login/verify", data={"email": "fresh@example.com", "code": code}
    )
    assert verify.status_code == 303
    assert verify.headers["location"] == "/app"
    signup.assert_awaited_once()
    assert signup.await_args.kwargs["owner_email"] == "fresh@example.com"


def test_org_switch_rejects_org_you_do_not_belong_to() -> None:
    client, _ = _build(orgs=_orgs((DEFAULT_ORG, OWNER_ID, "teamshared")))
    _login(client)
    resp = _app_post(client, "/app/orgs/switch", {"org_id": str(uuid.uuid4())})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/orgs"
    # No session cookie re-issued for a foreign org.
    assert not any("ts_session" in c for c in resp.headers.get_list("set-cookie"))


def test_org_switch_accepts_org_you_belong_to() -> None:
    other_org = uuid.uuid4()
    other_user = uuid.uuid4()
    client, _ = _build(
        orgs=_orgs((DEFAULT_ORG, OWNER_ID, "teamshared"), (other_org, other_user, "Side Co"))
    )
    _login(client)
    resp = _app_post(client, "/app/orgs/switch", {"org_id": str(other_org)})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app"
    assert any("ts_session" in c for c in resp.headers.get_list("set-cookie"))


def test_orgs_page_lists_orgs_and_switcher() -> None:
    other = uuid.uuid4()
    client, _ = _build(
        orgs=_orgs((DEFAULT_ORG, OWNER_ID, "teamshared"), (other, uuid.uuid4(), "Side Co"))
    )
    _login(client)
    resp = client.get("/app/orgs")
    assert resp.status_code == 200
    assert "Side Co" in resp.text
    assert "teamshared" in resp.text


def test_org_create_signs_up_and_switches(monkeypatch) -> None:
    new_org = uuid.uuid4()
    signup = AsyncMock(
        return_value=SimpleNamespace(
            org_id=new_org, owner_user_id=uuid.uuid4(),
            api_key=SimpleNamespace(prefix="tsk_x", token="tsk_x_y"),
        )
    )
    monkeypatch.setattr(console_mod, "signup_org", signup)
    client, _ = _build()
    _login(client)
    resp = _app_post(client, "/app/orgs/create", {"name": "New Team"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app"
    signup.assert_awaited_once()
    assert signup.await_args.kwargs["org_name"] == "New Team"


def test_people_add_member_redirects() -> None:
    client, services = _build()
    services.admin.add_member = AsyncMock(
        return_value={"user_id": "u9", "email": "new@team.io", "role": "member"}
    )
    _login(client)
    resp = _app_post(
        client, "/app/people/add", {"email": "new@team.io", "role": "member"}
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/people"
    services.admin.add_member.assert_awaited_once()
    assert services.admin.add_member.await_args.kwargs["email"] == "new@team.io"
    assert services.admin.add_member.await_args.kwargs["role"] == "member"


# --------------------------------------------------------------------------- #
# Consent UI (Phase 2)
# --------------------------------------------------------------------------- #
def _consent_stub() -> SimpleNamespace:
    return SimpleNamespace(
        list_grants=AsyncMock(
            return_value=[
                {
                    "id": "g1", "agent": "cursor", "mode": "policy",
                    "scope": ["tool_calls", "raw_turns"], "granted_by": str(OWNER_ID),
                    "granted_at": "2026-05-28T10:00:00+00:00", "expires_at": None,
                    "revoked_at": None, "status": "active",
                }
            ]
        ),
        grant=AsyncMock(return_value=uuid.uuid4()),
        revoke=AsyncMock(return_value=True),
    )


def test_consent_redirects_when_unauthed() -> None:
    client, _ = _build(consent=_consent_stub())
    resp = client.get("/app/consent")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_consent_page_lists_grants() -> None:
    consent = _consent_stub()
    client, _ = _build(consent=consent)
    _login(client)
    resp = client.get("/app/consent")
    assert resp.status_code == 200
    assert "Capture &amp; consent" in resp.text
    assert "cursor" in resp.text
    assert "tool_calls, raw_turns" in resp.text
    consent.list_grants.assert_awaited()


def test_consent_grant_posts_and_redirects() -> None:
    consent = _consent_stub()
    client, _ = _build(consent=consent)
    _login(client)
    resp = _app_post(
        client,
        "/app/consent/grant",
        {"agent": "hermes", "mode": "policy", "scope": "tool_calls"},
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/consent"
    consent.grant.assert_awaited_once()
    kwargs = consent.grant.await_args.kwargs
    assert kwargs["agent"] == "hermes"
    assert kwargs["mode"] == "policy"
    assert kwargs["scope"] == ["tool_calls"]


def test_consent_revoke_posts_and_redirects() -> None:
    consent = _consent_stub()
    client, _ = _build(consent=consent)
    _login(client)
    resp = _app_post(client, "/app/consent/g1/revoke")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/app/consent"
    consent.revoke.assert_awaited_once()
