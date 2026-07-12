"""Exercise every tool on the live teamshared MCP server and print a report."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError


@dataclass
class ToolResult:
    tool: str
    status: str  # pass | fail | skip | warn
    detail: str = ""
    ms: int = 0


@dataclass
class AuditReport:
    results: list[ToolResult] = field(default_factory=list)
    created: dict[str, Any] = field(default_factory=dict)

    def add(self, tool: str, status: str, detail: str = "", ms: int = 0) -> None:
        self.results.append(ToolResult(tool, status, detail, ms))


def _ok(data: Any) -> bool:
    if data is None:
        return False
    return not (isinstance(data, dict) and data.get("error"))


def unwrap_tool_payload(data: Any) -> Any:
    """Normalize MCP tool payloads for assertions.

    - Unwrap FastMCP ``{"result": ...}`` envelopes.
    - Parse JSON embedded in compression ``{"output": "..."}`` blobs.
    """
    if not isinstance(data, dict):
        return data

    if set(data.keys()) == {"result"}:
        return data["result"]

    output = data.get("output")
    if isinstance(output, str):
        parsed = _parse_json_from_compressed_output(output)
        if parsed is not None:
            return parsed

    if "result" in data and isinstance(data["result"], dict):
        return data["result"]

    return data


def _parse_json_from_compressed_output(text: str) -> Any | None:
    """Extract trailing JSON from a compressed teamshared tool output string."""
    start = text.find("{")
    if start < 0:
        return None
    blob = text[start:]
    # Drop trailing ref= line if present.
    if "\nref=" in blob:
        blob = blob.split("\nref=", 1)[0].rstrip()
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def payload_has_key(data: Any, key: str) -> bool:
    """True when ``key`` is present in structured or compressed tool output."""
    body = unwrap_tool_payload(data)
    if isinstance(body, dict) and key in body:
        return True
    if isinstance(data, dict):
        output = data.get("output")
        if isinstance(output, str) and f'"{key}"' in output:
            return True
    return False


def _has_name(data: Any, name: str) -> bool:
    body = unwrap_tool_payload(data)
    return isinstance(body, dict) and body.get("name") == name


def _is_dictish(data: Any) -> bool:
    body = unwrap_tool_payload(data)
    return body is None or isinstance(body, dict)


def _remember_ok(data: Any) -> bool:
    body = unwrap_tool_payload(data)
    if not isinstance(body, dict):
        return False
    return (
        body.get("count", 0) >= 1
        or body.get("status") in ("active", "duplicate")
        or bool(body.get("memory_id"))
        or bool(body.get("stored"))
    )


async def _timed(client: Client, tool: str, args: dict[str, Any] | None = None) -> tuple[Any, int, str | None]:
    start = time.perf_counter()
    try:
        result = await client.call_tool(tool, args or {})
        ms = int((time.perf_counter() - start) * 1000)
        err = None
        data = result.data
        if isinstance(data, dict) and data.get("error"):
            err = str(data["error"])
        return data, ms, err
    except ToolError as exc:
        ms = int((time.perf_counter() - start) * 1000)
        return None, ms, f"ToolError: {exc}"
    except Exception as exc:
        ms = int((time.perf_counter() - start) * 1000)
        return None, ms, f"{type(exc).__name__}: {exc}"


async def run_audit(url: str, token: str, repo: str, github: str) -> AuditReport:
    report = AuditReport()
    run_id = uuid.uuid4().hex[:8]
    marker = f"mcp-audit-{run_id}"
    skill_name = f"teamshared.audit-skill-{run_id}"
    playbook_name = f"teamshared.audit-playbook-{run_id}"
    state_key = f"audit/run-{run_id}"

    transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
    async with Client(transport) as client:
        tools_resp = await client.list_tools()
        tool_names = sorted(t.name for t in tools_resp)
        report.created["tool_count"] = len(tool_names)

        async def test(
            tool: str,
            args: dict[str, Any] | None = None,
            *,
            expect=None,
            warn_if: Any = None,
        ) -> Any:
            if tool not in tool_names:
                report.add(tool, "skip", "not advertised by server")
                return None
            data, ms, err = await _timed(client, tool, args)
            if err:
                report.add(tool, "fail", err[:200], ms)
                return None
            if expect is not None:
                try:
                    ok = expect(data)
                except Exception as exc:
                    report.add(tool, "fail", f"expect failed: {exc}", ms)
                    return data
                if not ok:
                    if warn_if is not None:
                        try:
                            if warn_if(unwrap_tool_payload(data)):
                                report.add(tool, "warn", str(data)[:200], ms)
                                return data
                        except Exception:
                            pass
                    report.add(tool, "fail", str(data)[:200], ms)
                    return data
            report.add(tool, "pass", "", ms)
            return data

        # --- infra / meta ---
        await test("health", expect=lambda d: d.get("status") in ("ok", "degraded"))
        await test("version", {"installed_rule_version": "1.8.0"}, expect=lambda d: "rule_version" in d)
        await test("memory_tools_catalog", {"scope": "memory", "tier": "core"}, expect=lambda d: d.get("count", 0) > 0)

        # --- context ---
        big_json = json.dumps({"rows": [{"id": i, "payload": "x" * 200} for i in range(40)]})
        await test(
            "context_normalize",
            {"tool_name": "Shell", "output": big_json},
            expect=lambda d: "output" in d,
        )
        compressed = await test(
            "context_compress",
            {
                "messages": [
                    {"role": "user", "content": "hello"},
                    {"role": "tool", "content": big_json},
                ]
            },
            expect=lambda d: "messages" in d,
        )
        ccr_ref = None
        if compressed and isinstance(compressed, dict):
            for msg in compressed.get("messages") or []:
                content = str(msg.get("content", ""))
                if "ccr_" in content:
                    for token_part in content.split():
                        if token_part.startswith("ccr_"):
                            ccr_ref = token_part.rstrip(")")
                            break
        if ccr_ref:
            await test("context_retrieve", {"ref": ccr_ref}, expect=lambda d: d is not None)
        else:
            report.add("context_retrieve", "warn", "no ccr ref produced (output may be below threshold)")

        session_id = None
        opened = await test(
            "memory_session_open",
            {"topic": f"audit {marker}", "repo": repo, "github": github},
            expect=lambda d: bool(d.get("session_id")),
        )
        if opened:
            session_id = opened["session_id"]
            report.created["session_id"] = session_id

        await test(
            "context_prepare",
            {
                "prompt": f"audit prompt {marker}",
                "session_id": session_id,
                "repo": repo,
                "github": github,
                "append_session": False,
                "enrich": True,
                "token_budget": 500,
            },
            expect=lambda d: "messages" in d,
        )

        # --- memory reads ---
        await test(
            "memory_recall",
            {"query": "teamshared", "k": 5, "repo": repo, "github": github},
            expect=lambda d: payload_has_key(d, "records"),
        )
        await test(
            "memory_episodes_list",
            {"limit": 5},
            expect=lambda d: payload_has_key(d, "episodes"),
        )
        await test(
            "memory_entity_view",
            {"slug": "teamshared"},
            expect=lambda d: payload_has_key(d, "slug")
            or payload_has_key(d, "entity")
            or (isinstance(unwrap_tool_payload(d), dict) and unwrap_tool_payload(d) == {}),
        )
        await test(
            "memory_assemble_context",
            {"task": f"audit {marker}", "token_budget": 800, "repo": repo, "github": github},
            expect=lambda d: isinstance(d, dict)
            and (
                isinstance(d.get("context_md", d.get("pack", "")), str)
                or "sections" in d
            ),
        )

        # --- procedures / skills ---
        await test(
            "memory_procedures_list",
            {"limit": 10},
            expect=lambda d: payload_has_key(d, "procedures") or payload_has_key(d, "count"),
        )
        await test(
            "memory_playbooks_list",
            {"limit": 10},
            expect=lambda d: payload_has_key(d, "playbooks")
            or payload_has_key(d, "procedures")
            or payload_has_key(d, "count"),
        )
        await test(
            "memory_procedure_get",
            {"name": "teamshared.start-of-task"},
            expect=lambda d: isinstance(d, dict) and d.get("name") == "teamshared.start-of-task",
            warn_if=lambda d: d is None or d == {} or not d.get("name"),
        )
        await test(
            "memory_playbook_get",
            {"name": "teamshared.start-of-task"},
            expect=lambda d: isinstance(d, dict) and d.get("name") == "teamshared.start-of-task",
            warn_if=lambda d: d is None or d == {} or not d.get("name"),
        )

        skill = await test(
            "memory_skill_set",
            {
                "name": skill_name,
                "body_md": f"# audit skill\n\nmarker `{marker}`\n",
                "tags": ["audit", "ephemeral"],
            },
            expect=lambda d: d.get("name") == skill_name,
        )
        if skill:
            report.created["skill_name"] = skill_name
            await test(
                "memory_skill_get",
                {"name": skill_name},
                expect=lambda d: _has_name(d, skill_name),
            )
            await test("memory_skills_list", {"limit": 20}, expect=lambda d: isinstance(d, dict))

        playbook = await test(
            "memory_playbook_set",
            {
                "name": playbook_name,
                "steps_md": f"# audit playbook\n\n1. marker `{marker}`\n",
                "tags": ["audit", "ephemeral"],
            },
            expect=lambda d: d.get("name") == playbook_name,
        )
        if playbook:
            report.created["playbook_name"] = playbook_name
            await test(
                "memory_playbook_get",
                {"name": playbook_name},
                expect=lambda d: _has_name(d, playbook_name),
            )
            if skill:
                await test(
                    "memory_skill_resolve",
                    {"playbook_name": playbook_name},
                    expect=lambda d: isinstance(d, dict),
                )

        # alias writes
        alias_pb = f"teamshared.audit-proc-alias-{run_id}"
        await test(
            "memory_procedure_set",
            {"name": alias_pb, "steps_md": f"alias {marker}", "tags": ["audit"]},
            expect=lambda d: d.get("name") == alias_pb,
        )
        report.created["alias_playbook"] = alias_pb

        # --- semantic / episodic ---
        remembered = await test(
            "memory_remember",
            {
                "content": f"{marker}: audit preference for MCP tool verification.",
                "kind": "preference",
                "tags": ["audit", marker],
                "repo": repo,
                "github": github,
            },
            expect=lambda d: _remember_ok(d),
        )
        mem_ids: list[str] = []
        if remembered:
            body = unwrap_tool_payload(remembered)
            if isinstance(body, dict):
                for item in body.get("stored") or []:
                    if item.get("id"):
                        mem_ids.append(str(item["id"]))
                if body.get("memory_id"):
                    mem_ids.append(str(body["memory_id"]))

        await test(
            "memory_remember",
            {
                "content": f"{marker}: audit episodic event.",
                "kind": "event",
                "tags": ["audit", marker],
            },
            expect=lambda d: _remember_ok(d),
        )

        # --- session lifecycle ---
        if session_id:
            await test(
                "memory_session_append",
                {"session_id": session_id, "role": "user", "content": f"audit turn {marker}"},
                expect=lambda d: d.get("turn_count", 0) >= 1,
            )
            await test("memory_session_get", {"session_id": session_id}, expect=lambda d: d.get("session_id") == session_id)
            await test(
                "memory_session_close",
                {"session_id": session_id, "distill": False},
                expect=lambda d: d.get("session_id") == session_id,
            )

        # --- think (may be slow) ---
        await test(
            "memory_think",
            {"query": f"what is {marker}", "k": 5, "repo": repo, "github": github},
            expect=lambda d: payload_has_key(d, "answer_md"),
        )

        # --- graph ---
        graph_write = await test(
            "memory_graph_relate",
            {"subject": marker, "predicate": "audited_by", "object_entity": "teamshared"},
        )
        if graph_write and graph_write.get("reason") == "graph_disabled":
            report.results[-1].status = "warn"
            report.results[-1].detail = "graph_disabled"
            gr = await test("memory_graph_related", {"name": marker, "depth": 1})
            if gr and gr.get("reason") == "graph_disabled":
                report.results[-1].status = "warn"
                report.results[-1].detail = "graph_disabled"
        else:
            await test("memory_graph_related", {"name": marker, "depth": 1}, expect=lambda d: isinstance(d, dict))

        # --- state ---
        state_val = {"marker": marker}
        await test(
            "memory_state_set",
            {"repo": repo, "key": state_key, "value": state_val},
            expect=lambda d: d is not None,
        )
        await test(
            "memory_state_get",
            {"repo": repo, "key": state_key},
            expect=lambda d: isinstance(d, dict) and d.get("value") == state_val,
        )

        # --- ontology ---
        await test("memory_ontology_list", expect=lambda d: isinstance(d, dict))
        await test(
            "memory_ontology_propose_entity",
            {"name": f"Audit Entity {run_id}", "kind_name": "entity"},
            expect=lambda d: isinstance(d, dict),
        )
        await test(
            "memory_ontology_link_type_set",
            {
                "name": f"audit_link_{run_id}",
                "description": "audit link",
                "from_kinds": ["entity"],
                "to_kinds": ["entity"],
            },
            expect=lambda d: isinstance(d, dict),
        )
        await test(
            "memory_ontology_object_kind_set",
            {"name": f"audit_kind_{run_id}", "description": "audit kind"},
            expect=lambda d: isinstance(d, dict),
        )
        await test("memory_action_log_list", {"limit": 5}, expect=lambda d: isinstance(d, dict))

        # --- strategic ---
        await test("memory_strategic_statement_get", {"kind": "mission"}, expect=lambda d: isinstance(d, dict))
        await test("memory_strategic_plan_list", {"limit": 5}, expect=lambda d: isinstance(d, dict))
        plan = await test(
            "memory_strategic_plan_set",
            {
                "name": f"audit-plan-{run_id}",
                "period_start": "2026-01-01",
                "period_end": "2026-03-31",
            },
            expect=lambda d: isinstance(d, dict) and (d.get("plan_id") or d.get("id") or d.get("name")),
        )
        plan_id = None
        if plan:
            plan_id = plan.get("plan_id") or plan.get("id")
            if plan_id:
                await test("memory_strategic_plan_get", {"plan_id": plan_id}, expect=lambda d: isinstance(d, dict))
        if plan_id:
            await test(
                "memory_strategic_entity_get",
                {"entity_type": "plan", "entity_id": str(plan_id)},
                expect=lambda d: d is None or isinstance(d, dict),
            )
        else:
            report.add("memory_strategic_entity_get", "skip", "no plan id from plan_set")

        # --- work + projects ---
        project = await test(
            "project_create",
            {"name": f"Audit Project {run_id}", "description_md": marker},
            expect=lambda d: bool(d.get("project_id") or d.get("id")),
        )
        project_id = None
        if project:
            project_id = project.get("project_id") or project.get("id")
            report.created["project_id"] = project_id
            await test("project_list", {"limit": 10}, expect=lambda d: isinstance(d, dict))
            await test("project_get", {"project_id": project_id}, expect=lambda d: isinstance(d, dict))
            section = await test(
                "project_section_add",
                {"project_id": project_id, "name": "Audit"},
                expect=lambda d: bool(d.get("section_id") or d.get("id")),
            )
            section_id = section.get("section_id") or section.get("id") if section else None
            await test("project_section_list", {"project_id": project_id}, expect=lambda d: isinstance(d, dict))
            await test(
                "project_status_post",
                {"project_id": project_id, "body_md": f"audit status {marker}"},
                expect=lambda d: _is_dictish(d),
            )
            await test(
                "project_update",
                {"project_id": project_id, "description_md": f"updated {marker}"},
                expect=lambda d: _is_dictish(d),
            )

        work = await test(
            "work_create",
            {"title": f"Audit task {marker}", "work_status": "todo", "description": marker},
            expect=lambda d: bool(d.get("work_id") or d.get("id")),
        )
        work_id = None
        if work:
            work_id = work.get("work_id") or work.get("id")
            report.created["work_id"] = work_id
            await test("work_list", {"limit": 10}, expect=lambda d: isinstance(d, dict))
            await test("work_get", {"work_id": work_id}, expect=lambda d: isinstance(d, dict))
            await test(
                "work_update",
                {"work_id": work_id, "work_status": "in_progress"},
                expect=lambda d: isinstance(d, dict),
            )
            await test(
                "work_comment_add",
                {"work_id": work_id, "body": f"audit comment {marker}"},
                expect=lambda d: isinstance(d, dict),
            )
            await test("work_comment_list", {"work_id": work_id}, expect=lambda d: isinstance(d, dict))
            await test("work_follower_add", {"work_id": work_id}, expect=lambda d: isinstance(d, dict))
            await test("work_followers_list", {"work_id": work_id}, expect=lambda d: isinstance(d, dict))
            await test("work_follower_remove", {"work_id": work_id}, expect=lambda d: isinstance(d, dict))
            await test("work_subtasks_list", {"work_id": work_id}, expect=lambda d: isinstance(d, dict))
            await test(
                "work_dependencies_list",
                {"work_id": work_id},
                expect=lambda d: d is None or isinstance(d, dict),
            )
            if project_id:
                await test(
                    "work_add_to_project",
                    {"work_id": work_id, "project_id": project_id, "section_id": section_id},
                    expect=lambda d: isinstance(d, dict),
                )
                await test(
                    "work_move",
                    {
                        "work_id": work_id,
                        "project_id": project_id,
                        "section_id": section_id,
                    },
                    expect=lambda d: _is_dictish(d),
                )
                await test(
                    "work_remove_from_project",
                    {"work_id": work_id, "project_id": project_id},
                    expect=lambda d: isinstance(d, dict),
                )
            await test(
                "work_close",
                {"work_id": work_id, "work_status": "done"},
                expect=lambda d: isinstance(d, dict),
            )

        # --- new session tools ---
        ens = await test(
            "memory_session_ensure",
            {
                "repo": repo,
                "topic": f"ensure {marker}",
                "github": github,
                "fresh": True,
                "user": f"audit user turn {marker}",
            },
            expect=lambda d: bool(d.get("session_id")) and d.get("turn_count", 0) >= 1,
        )
        if ens:
            await test(
                "context_commit",
                {
                    "summary": f"audit summary {marker}",
                    "session_id": ens["session_id"],
                    "repo": repo,
                    "close": True,
                },
                expect=lambda d: isinstance(d, dict),
            )

        # --- cleanup ---
        if mem_ids:
            await test(
                "memory_forget",
                {"memory_id": mem_ids[0], "reason": f"audit cleanup {run_id}"},
                expect=lambda d: d.get("deleted") is True,
            )
        if skill_name in (report.created.get("skill_name"),):
            await test(
                "memory_forget_skill",
                {"name": skill_name, "reason": f"audit cleanup {run_id}"},
                expect=lambda d: isinstance(d, dict),
            )
        for pb_name in (playbook_name, alias_pb):
            await test(
                "memory_forget_procedure",
                {"name": pb_name, "reason": f"audit cleanup {run_id}"},
                expect=lambda d: isinstance(d, dict),
            )
        if project_id:
            await test(
                "project_archive",
                {"project_id": project_id},
                expect=lambda d: isinstance(d, dict),
            )

        # mark tools we never explicitly called
        tested = {r.tool for r in report.results}
        for name in tool_names:
            if name == "mcp_auth":
                report.add(name, "skip", "auth helper, not exercised")
            elif name not in tested:
                report.add(name, "skip", "not covered by audit script")

    return report


def _print_report(report: AuditReport) -> int:
    by_status: dict[str, list[ToolResult]] = {"pass": [], "fail": [], "warn": [], "skip": []}
    for r in report.results:
        by_status.setdefault(r.status, []).append(r)

    print()
    print("=" * 72)
    print("TEAMSHARED MCP TOOL AUDIT")
    print("=" * 72)
    for status in ("pass", "warn", "fail", "skip"):
        items = by_status.get(status, [])
        if not items:
            continue
        print(f"\n{status.upper()} ({len(items)})")
        print("-" * 72)
        for r in sorted(items, key=lambda x: x.tool):
            detail = f" — {r.detail}" if r.detail else ""
            timing = f" [{r.ms}ms]" if r.ms else ""
            print(f"  {r.tool}{timing}{detail}")

    total = len(report.results)
    passed = len(by_status["pass"])
    failed = len(by_status["fail"])
    warned = len(by_status["warn"])
    skipped = len(by_status["skip"])
    print()
    print("=" * 72)
    print(f"Tools advertised: {report.created.get('tool_count', '?')}")
    print(f"Results: {passed} pass, {warned} warn, {failed} fail, {skipped} skip (total {total})")
    print("=" * 72)
    return 1 if failed else 0


def main() -> None:
    url = os.environ.get("TEAMSHARED_SMOKE_URL", "https://teamshared.com/mcp/")
    token = os.environ.get("TEAMSHARED_SMOKE_TOKEN")
    repo = os.environ.get("TEAMSHARED_SMOKE_REPO", "Users-chad-code-xhad-teamshared")
    github = os.environ.get("TEAMSHARED_SMOKE_GITHUB", "xhad/teamshared")
    if not token:
        print("Set TEAMSHARED_SMOKE_TOKEN", file=sys.stderr)
        sys.exit(2)
    if not url.endswith("/"):
        url += "/"
    report = asyncio.run(run_audit(url, token, repo, github))
    sys.exit(_print_report(report))


if __name__ == "__main__":
    main()
