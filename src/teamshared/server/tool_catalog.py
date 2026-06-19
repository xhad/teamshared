"""MCP tool catalog for agent discovery.

Grouped, tiered descriptions agents can fetch via ``memory_tools_catalog`` instead
of scanning every tool descriptor in the client.
"""

from __future__ import annotations

from typing import Any, Literal

ToolTier = Literal["core", "extended", "human"]

_CATALOG: list[dict[str, Any]] = [
    # --- ops ---
    {"name": "health", "tier": "core", "group": "ops",
     "summary": "Liveness + dependency probe", "example": {}},
    {"name": "version", "tier": "core", "group": "ops",
     "summary": "Server + memory-rule version check",
     "example": {"installed_rule_version": "1.5.0"}},
    {"name": "memory_tools_catalog", "tier": "core", "group": "ops",
     "summary": "List tools by tier/group with examples",
     "example": {"scope": "memory", "tier": "core"}},
    # --- memory core ---
    {"name": "memory_recall", "tier": "core", "group": "memory",
     "summary": "Hybrid search — raw ranked records (use memory_think for answers)",
     "example": {"query": "how do we deploy", "repo": "Users-me-code-myrepo", "k": 8}},
    {"name": "memory_think", "tier": "core", "group": "memory",
     "summary": "Synthesized answer with citations and gap analysis",
     "example": {"query": "what do I need before the Acme meeting", "k": 12}},
    {"name": "memory_remember", "tier": "core", "group": "memory",
     "summary": "Write fact/preference/event/note (not skill/playbook)",
     "example": {"content": "Postgres on host 5433", "kind": "fact", "repo": "Users-me-code-myrepo"}},
    {"name": "memory_assemble_context", "tier": "core", "group": "memory",
     "summary": "One token-budgeted context pack for a task",
     "example": {"task": "fix flaky CI test", "token_budget": 1500}},
    {"name": "memory_session_open", "tier": "core", "group": "memory",
     "summary": "Open working-memory session for this chat",
     "example": {"topic": "debug retrieval bug", "repo": "Users-me-code-myrepo"}},
    {"name": "memory_session_append", "tier": "core", "group": "memory",
     "summary": "Append a turn to the session",
     "example": {"session_id": "sess_abc", "role": "user", "content": "fix the bug"}},
    {"name": "memory_session_close", "tier": "core", "group": "memory",
     "summary": "Close session and enqueue distillation",
     "example": {"session_id": "sess_abc", "distill": True}},
    {"name": "memory_session_get", "tier": "extended", "group": "memory",
     "summary": "Read session metadata and turns (debug/handoff)",
     "example": {"session_id": "sess_abc"}},
    {"name": "memory_episodes_list", "tier": "extended", "group": "memory",
     "summary": "Browse episodic timeline",
     "example": {"limit": 20}},
    {"name": "memory_forget", "tier": "extended", "group": "memory",
     "summary": "Soft-delete semantic/episodic memory by id",
     "example": {"memory_id": "<uuid>", "reason": "duplicate fact"}},
    {"name": "memory_approval_status", "tier": "extended", "group": "memory",
     "summary": "Check pending_approval/quarantined write status",
     "example": {"skill_id": "42"}},
    {"name": "memory_state_get", "tier": "extended", "group": "memory",
     "summary": "Read token+repo scoped JSON state",
     "example": {"repo": "Users-me-code-myrepo", "key": "conversation/active-session"}},
    {"name": "memory_state_set", "tier": "extended", "group": "memory",
     "summary": "Write token+repo scoped JSON state",
     "example": {"repo": "Users-me-code-myrepo", "key": "conversation/active-session",
                 "value": {"session_id": "sess_abc"}}},
    # --- skills (building blocks) ---
    {"name": "memory_skill_get", "tier": "core", "group": "skills",
     "summary": "Fetch atomic skill by name",
     "example": {"name": "ship-pr"}},
    {"name": "memory_skill_set", "tier": "extended", "group": "skills",
     "summary": "Store new skill version (building block)",
     "example": {"name": "ship-pr", "body_md": "# Ship PR\n1. Run tests\n2. Open PR"}},
    {"name": "memory_skills_list", "tier": "core", "group": "skills",
     "summary": "List skills (summaries by default)",
     "example": {"limit": 50, "offset": 0}},
    {"name": "memory_skill_resolve", "tier": "core", "group": "skills",
     "summary": "Resolve playbook skill refs to full bodies",
     "example": {"playbook_name": "release-loop"}},
    {"name": "memory_forget_skill", "tier": "extended", "group": "skills",
     "summary": "Soft-delete all versions of a skill by name",
     "example": {"name": "old-skill", "reason": "superseded"}},
    # --- playbooks (procedures) ---
    {"name": "memory_procedure_get", "tier": "core", "group": "playbooks",
     "summary": "Fetch playbook; use expand_skills to inline skill bodies",
     "example": {"name": "teamshared.start-of-task", "expand_skills": True}},
    {"name": "memory_playbook_get", "tier": "core", "group": "playbooks",
     "summary": "Alias for memory_procedure_get",
     "example": {"name": "ship-pr", "expand_skills": True}},
    {"name": "memory_procedure_set", "tier": "extended", "group": "playbooks",
     "summary": "Store playbook; compose skills via tool_recipe.skills",
     "example": {
         "name": "release-loop",
         "steps_md": "# Release\nRun lint then ship.",
         "tool_recipe": {"skills": ["lint", "ship-pr"], "loop": {"max_iterations": 3}},
     }},
    {"name": "memory_playbook_set", "tier": "extended", "group": "playbooks",
     "summary": "Alias for memory_procedure_set", "example": {"name": "release-loop", "steps_md": "..."}},
    {"name": "memory_procedures_list", "tier": "core", "group": "playbooks",
     "summary": "List playbooks (summaries unless include_body=true)",
     "example": {"limit": 50, "offset": 0}},
    {"name": "memory_playbooks_list", "tier": "core", "group": "playbooks",
     "summary": "Alias for memory_procedures_list", "example": {"limit": 50}},
    {"name": "memory_forget_procedure", "tier": "extended", "group": "playbooks",
     "summary": "Soft-delete all versions of a playbook by name",
     "example": {"name": "old-playbook", "reason": "retired"}},
    # --- graph ---
    {"name": "memory_graph_relate", "tier": "extended", "group": "graph",
     "summary": "Add explicit entity relationship (Neo4j when enabled)",
     "example": {"subject": "alice", "predicate": "works_on", "object_entity": "teamshared"}},
    {"name": "memory_graph_related", "tier": "extended", "group": "graph",
     "summary": "Walk graph neighbors",
     "example": {"name": "teamshared", "depth": 2}},
    {"name": "memory_entity_view", "tier": "core", "group": "graph",
     "summary": "Entity hub — wiki + memories + graph + work rollup",
     "example": {"slug": "teamshared"}},
    {"name": "memory_ontology_list", "tier": "extended", "group": "graph",
     "summary": "Org link types, object kinds, interfaces, action types",
     "example": {}},
    {"name": "memory_ontology_propose_entity", "tier": "extended", "group": "graph",
     "summary": "Propose a typed ontology entity",
     "example": {"kind_name": "Project", "name": "Acme rollout"}},
    # --- strategic ---
    {"name": "memory_strategic_statement_get", "tier": "extended", "group": "strategic",
     "summary": "Active vision/mission/purpose", "example": {"kind": "mission"}},
    {"name": "memory_strategic_plan_list", "tier": "extended", "group": "strategic",
     "summary": "List OKR cycles", "example": {"active_only": True}},
    {"name": "memory_strategic_plan_get", "tier": "extended", "group": "strategic",
     "summary": "Fetch plan with optional OKR tree", "example": {"plan_id": "<uuid>"}},
    {"name": "memory_strategic_entity_get", "tier": "extended", "group": "strategic",
     "summary": "Fetch objective, key_result, or initiative by id",
     "example": {"entity_type": "objective", "entity_id": "<uuid>"}},
    # --- work ---
    {"name": "work_list", "tier": "core", "group": "work",
     "summary": "List org tasks", "example": {"mine": True, "limit": 50, "offset": 0}},
    {"name": "work_get", "tier": "core", "group": "work",
     "summary": "Fetch one task", "example": {"work_id": "<uuid>"}},
    {"name": "work_create", "tier": "core", "group": "work",
     "summary": "Create task (active immediately)",
     "example": {"title": "Fix CI", "work_status": "todo", "assignee_agent": "cursor"}},
    {"name": "work_update", "tier": "core", "group": "work",
     "summary": "Update task fields/status", "example": {"work_id": "<uuid>", "work_status": "in_progress"}},
    {"name": "work_close", "tier": "core", "group": "work",
     "summary": "Mark done/cancelled", "example": {"work_id": "<uuid>", "work_status": "done"}},
    {"name": "work_comment_add", "tier": "core", "group": "work",
     "summary": "Add progress comment", "example": {"work_id": "<uuid>", "body": "PR opened"}},
    # --- agent runs / workflows (extended) ---
    {"name": "agent_run_create", "tier": "extended", "group": "agent_runs",
     "summary": "Queue background agent run on a task",
     "example": {"work_id": "<uuid>", "agent": "cursor", "playbook_name": "ship-pr"}},
    {"name": "workflow_start", "tier": "human", "group": "workflows",
     "summary": "Start procedural-loop workflow run", "example": {"workflow_name": "review-loop"}},
]

_TOOL_RECIPE_HELP = {
    "skills_compose": {
        "description": "Playbook that loops through skill building blocks",
        "example": {
            "skills": ["lint", "ship-pr"],
            "skill_versions": {"ship-pr": 2},
            "loop": {"max_iterations": 3},
        },
    },
    "workflow_stages": {
        "description": "Multi-stage workflow graph stored on a procedure",
        "example": {
            "stages": [
                {"id": "triage", "owner": "agent", "agent": "cursor", "skill": "triage",
                 "advance": "auto", "on_done": "implement"},
                {"id": "implement", "owner": "agent", "playbook": "ship-pr",
                 "advance": "auto", "on_done": "done"},
            ],
            "loop": {"select": {"work_status": "todo"}, "until": "all_terminal",
                     "max_iterations": 10},
        },
    },
}


def list_tools(
    *,
    scope: str = "all",
    tier: str | None = None,
) -> dict[str, Any]:
    """Return grouped tool metadata for MCP discovery."""
    groups = {"memory", "skills", "playbooks", "graph", "strategic", "work",
              "agent_runs", "workflows", "ops", "projects"}
    if scope == "memory":
        groups = {"memory", "skills", "playbooks", "graph", "strategic", "ops"}
    elif scope == "work":
        groups = {"work", "agent_runs", "workflows", "projects"}

    entries = [
        e for e in _CATALOG
        if e["group"] in groups and (tier is None or e["tier"] == tier)
    ]
    by_group: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_group.setdefault(entry["group"], []).append(entry)
    return {
        "count": len(entries),
        "tool_recipe_shapes": _TOOL_RECIPE_HELP,
        "groups": by_group,
        "tiers": {
            "core": "Use every session (recall, remember, sessions, skills, playbooks, work)",
            "extended": "Writes, graph, strategic, agent runs, debugging",
            "human": "Workflow orchestration and human gates",
        },
    }
