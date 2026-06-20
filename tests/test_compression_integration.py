"""Integration tests measuring compression token savings on realistic payloads.

Requires compose Postgres + Redis (``make build``, ``make migrate``) and env from
``.env`` (host Postgres often on 5433).

Run:

    pytest -m integration tests/test_compression_integration.py -v -s
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from starlette.requests import Request
from starlette.testclient import TestClient

from teamshared.auth import AgentIdentity, _current_agent, _current_principal
from teamshared.compress.ccr_store import org_scope_from_id
from teamshared.compress.engine import compress_messages_with_ccr
from teamshared.compress.factory import ccr_store_from_working
from teamshared.compress.tool_output import normalize_tool_output
from teamshared.config import get_settings
from teamshared.identity.accounts import AccountStore
from teamshared.identity.api_keys import ApiKeyStore
from teamshared.identity.provisioning import signup_org
from teamshared.identity.principal import Principal
from teamshared.identity.roles import RoleStore
from teamshared.memory.working import WorkingMemory
from teamshared.server import state as state_mod
from teamshared.server.app import build_http_app
from teamshared.server.compress_api import handle_compress_retrieve
from teamshared.tenancy.context import TenantDb
from teamshared.tenancy.repository import TenancyRepository
from tests.compression_benchmarks import (
    CompressionScenario,
    SavingsReport,
    compression_scenarios,
    format_savings_table,
    token_estimate_for_messages,
    token_estimate_for_text,
    token_reduction_pct,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def integration_stack() -> Any:
    """Real Redis + Postgres; mint a bearer token for HTTP tests."""
    settings = get_settings()
    working = WorkingMemory(settings.redis_url, default_ttl=settings.session_ttl)
    try:
        await working.connect()
        await working.client.ping()
    except Exception as exc:
        pytest.skip(f"Redis unavailable: {exc}")

    db = TenantDb(settings.pg_app_dsn)
    try:
        await db.connect()
    except Exception as exc:
        await working.close()
        pytest.skip(f"Postgres unavailable: {exc}")

    repo = TenancyRepository(db)
    keys = ApiKeyStore(db)
    roles = RoleStore(db)
    accounts = AccountStore(db)
    slug = f"compress-{uuid.uuid4().hex[:8]}"
    try:
        signup = await signup_org(
            repo=repo,
            api_keys=keys,
            roles=roles,
            accounts=accounts,
            org_slug=slug,
            org_name="Compression IT",
            owner_email=f"owner-{slug}@compress.test",
        )
    except Exception as exc:
        await working.close()
        await db.close()
        pytest.skip(f"Postgres signup failed: {exc}")

    store = ccr_store_from_working(settings, working)
    org_scope = org_scope_from_id(signup.org_id)

    stack = type(
        "Stack",
        (),
        {
            "settings": settings,
            "working": working,
            "store": store,
            "org_scope": org_scope,
            "org_id": signup.org_id,
            "token": signup.api_key.token,
            "db": db,
        },
    )()

    yield stack

    await working.close()
    await db.close()


def _message_chars(messages: list[dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
    return total


def _body_chars(body: Any) -> int:
    if isinstance(body, str):
        return len(body)
    return len(json.dumps(body, separators=(",", ":"), default=str))


async def _run_scenario_on_engine(stack: Any, scenario: CompressionScenario) -> SavingsReport:
    settings = stack.settings

    if scenario.kind == "messages":
        messages = scenario.payload
        original_tokens = token_estimate_for_messages(messages)
        original_chars = _message_chars(messages)
        result = await compress_messages_with_ccr(
            settings,
            messages,
            org_scope=stack.org_scope,
            store=stack.store,
        )
        result_chars = _message_chars(result.messages)
        result_tokens = token_estimate_for_messages(result.messages)
        return SavingsReport(
            scenario=scenario.name,
            original_chars=original_chars,
            result_chars=result_chars,
            original_tokens=original_tokens,
            result_tokens=result_tokens,
            token_reduction_pct=token_reduction_pct(original_tokens, result_tokens),
            chars_saved=result.stats.chars_saved,
            compressed=result.compressed,
            ref=result.stats.refs[0] if result.stats.refs else None,
        )

    output = scenario.payload
    original_tokens = token_estimate_for_text(
        output if isinstance(output, str) else json.dumps(output)
    )
    original_chars = len(output) if isinstance(output, str) else len(json.dumps(output))
    normalized = await normalize_tool_output(
        settings,
        scenario.tool_name,
        output,
        org_scope=stack.org_scope,
        store=stack.store,
    )
    result_chars = _body_chars(normalized.body)
    result_text = (
        normalized.body
        if isinstance(normalized.body, str)
        else json.dumps(normalized.body, separators=(",", ":"), default=str)
    )
    result_tokens = token_estimate_for_text(result_text)
    return SavingsReport(
        scenario=scenario.name,
        original_chars=original_chars,
        result_chars=result_chars,
        original_tokens=original_tokens,
        result_tokens=result_tokens,
        token_reduction_pct=token_reduction_pct(original_tokens, result_tokens),
        chars_saved=normalized.chars_saved,
        compressed=normalized.compressed,
        cleaned=normalized.cleaned,
        ref=normalized.ref,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", compression_scenarios(), ids=lambda s: s.name)
async def test_compression_token_savings_engine(
    integration_stack: Any, scenario: CompressionScenario
) -> None:
    """Each scenario must meet minimum token/char savings on real Redis CCR."""
    report = await _run_scenario_on_engine(integration_stack, scenario)
    report.assert_meets(scenario)


@pytest.mark.asyncio
async def test_compression_token_savings_summary_report(integration_stack: Any) -> None:
    """Print an aggregate savings table (``pytest -s``) and assert overall win on fat payloads."""
    reports: list[SavingsReport] = []
    for scenario in compression_scenarios():
        reports.append(await _run_scenario_on_engine(integration_stack, scenario))

    print("\n" + format_savings_table(reports) + "\n")

    fat = [
        r
        for r in reports
        if r.scenario in {"grep_json_500_rows", "memory_recall_normalize", "multi_turn_tool_thread"}
    ]
    assert fat, "expected fat scenarios in report"
    for report in fat:
        assert report.token_reduction_pct >= 40.0, report.scenario
        assert report.chars_saved >= 1000, report.scenario

    protected = [r for r in reports if "protected" in r.scenario or "passthrough" in r.scenario]
    for report in protected:
        assert report.token_reduction_pct < 5.0, report.scenario


@pytest.mark.asyncio
async def test_ccr_roundtrip_after_compression(integration_stack: Any) -> None:
    """Compressed tool output stores originals in Redis; retrieve expands them."""
    settings = integration_stack.settings
    big = json.dumps([{"n": i, "msg": f"row {i}"} for i in range(120)])
    messages = [{"role": "tool", "content": big}]
    result = await compress_messages_with_ccr(
        settings,
        messages,
        org_scope=integration_stack.org_scope,
        store=integration_stack.store,
    )
    assert result.compressed is True
    assert result.stats.refs, "expected CCR ref"
    ref = result.stats.refs[0]

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/compress/retrieve",
        "query_string": f"ref={ref}".encode(),
        "headers": [],
    }

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive)
    token_agent = _current_agent.set(AgentIdentity(agent="cursor", state_id="compress-it"))
    token_principal = _current_principal.set(
        Principal(
            org_id=integration_stack.org_id,
            type="agent",
            id=uuid.uuid4(),
            display="cursor",
        )
    )
    state_mod.set_state(
        type(
            "S",
            (),
            {
                "settings": settings,
                "working": integration_stack.working,
            },
        )()
    )
    try:
        response = await handle_compress_retrieve(request)
    finally:
        _current_agent.reset(token_agent)
        _current_principal.reset(token_principal)

    assert response.status_code == 200
    body = json.loads(response.body)
    assert body["ref"] == ref
    assert body["content"] == big


def test_compress_http_endpoint_matches_engine(integration_stack: Any) -> None:
    """POST /compress over HTTP yields similar savings to the engine path."""
    scenario = next(s for s in compression_scenarios() if s.name == "grep_json_500_rows")
    messages = scenario.payload
    original_tokens = token_estimate_for_messages(messages)

    app = build_http_app(integration_stack.settings)
    with TestClient(app) as client:
        resp = client.post(
            "/compress",
            json={"messages": messages},
            headers={"Authorization": f"Bearer {integration_stack.token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["compressed"] is True
    result_tokens = token_estimate_for_messages(data["messages"])
    reduction = token_reduction_pct(original_tokens, result_tokens)
    assert reduction >= scenario.min_token_reduction_pct
    assert data["stats"]["chars_saved"] >= scenario.min_chars_saved


def test_tools_normalize_http_endpoint(integration_stack: Any) -> None:
    """POST /tools/normalize cleans recall payloads over HTTP."""
    scenario = next(s for s in compression_scenarios() if s.name == "memory_recall_normalize")
    app = build_http_app(integration_stack.settings)
    with TestClient(app) as client:
        resp = client.post(
            "/tools/normalize",
            json={"tool_name": scenario.tool_name, "output": scenario.payload},
            headers={"Authorization": f"Bearer {integration_stack.token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["cleaned"] is True
    assert data["stats"]["chars_saved"] >= scenario.min_chars_saved
    body = json.dumps(data["output"])
    assert "embedding" not in body


def test_llm_prepare_compresses_tool_history_not_context(integration_stack: Any) -> None:
    """POST /llm/prepare compresses incoming tool bloat; enrich disabled for this check."""
    scenario = next(s for s in compression_scenarios() if s.name == "multi_turn_tool_thread")
    original_tokens = token_estimate_for_messages(scenario.payload)

    app = build_http_app(integration_stack.settings)
    with TestClient(app) as client:
        resp = client.post(
            "/llm/prepare",
            json={
                "messages": scenario.payload,
                "repo": "Users-chad-code-sapien-teamshared",
                "append_session": False,
                "enrich": False,
            },
            headers={"Authorization": f"Bearer {integration_stack.token}"},
        )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["stats"]["compressed"] is True
    result_tokens = token_estimate_for_messages(data["messages"])
    reduction = token_reduction_pct(original_tokens, result_tokens)
    assert reduction >= 40.0
