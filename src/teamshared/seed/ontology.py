"""Bundled org ontology seeds: link types, object kinds, interfaces, action types."""

from __future__ import annotations

from typing import Any

# P1 — registered link predicates (autolink + memory_graph_relate)
STARTER_LINK_TYPES: list[tuple[str, str, list[str], list[str], str]] = [
    ("mentions", "Source entity references target in prose", [], [], "many_to_many"),
    ("works_at", "Person employed by organization", ["Person"], ["Organization"], "many_to_many"),
    ("works_on", "Entity contributes to project or repo", [], ["Project", "Repository"], "many_to_many"),
    ("owns", "Entity owns or is accountable for target", [], [], "one_to_many"),
    ("assigned_to", "Work or task assigned to person or agent", ["WorkItem"], ["Person", "Agent"], "many_to_many"),
    ("blocked_by", "Entity blocked by another entity", [], [], "many_to_many"),
    ("parent_of", "Hierarchical containment", [], [], "one_to_many"),
    ("related_to", "Generic association when no specific type fits", [], [], "many_to_many"),
]

# P3 — core object kinds
STARTER_OBJECT_KINDS: list[tuple[str, str, dict[str, Any]]] = [
    ("Person", "A human teammate", {"email": "string", "name": "string"}),
    ("Agent", "An AI agent identity", {"name": "string", "type": "string"}),
    ("Project", "A team project or initiative container", {"name": "string", "status": "string"}),
    ("Repository", "A git repository", {"github": "string", "slug": "string"}),
    ("Initiative", "A strategic initiative", {"title": "string", "status": "string"}),
    ("Memory", "A durable memory record", {"kind": "string", "subject": "string"}),
    ("WorkItem", "A task in the work queue", {"title": "string", "work_status": "string"}),
    ("Skill", "An atomic agent skill", {"name": "string"}),
    ("Playbook", "An orchestration playbook", {"name": "string"}),
    ("Organization", "A company or team org unit", {"name": "string"}),
]

# P4 — cross-pillar interfaces
STARTER_INTERFACES: list[tuple[str, str, list[str]]] = [
    ("Approvable", "Requires human approval before activation", ["approval_status", "requested_by"]),
    ("Assignable", "Can be assigned to a person or agent", ["assignee_type", "assignee_id"]),
    ("Scoped", "Scoped to a workspace or GitHub repo", ["repo", "github"]),
    ("Temporal", "Has a timeline of events", ["created_at", "updated_at"]),
]

# kind_name -> interface names
KIND_INTERFACE_MAP: dict[str, list[str]] = {
    "WorkItem": ["Assignable", "Approvable", "Temporal"],
    "Initiative": ["Assignable", "Approvable", "Scoped", "Temporal"],
    "Memory": ["Approvable", "Scoped", "Temporal"],
    "Person": ["Assignable", "Temporal"],
    "Agent": ["Assignable", "Temporal"],
    "Project": ["Scoped", "Temporal"],
    "Repository": ["Scoped", "Temporal"],
    "Skill": ["Approvable", "Temporal"],
    "Playbook": ["Approvable", "Temporal"],
}

# P2 — governed action types wrapping high-risk MCP mutations
STARTER_ACTION_TYPES: list[tuple[str, str, str, dict[str, Any], bool]] = [
    (
        "remember_fact",
        "Store a durable semantic fact with PII scan",
        "memory_remember",
        {"required": ["content"], "properties": {"content": {"type": "string"}, "kind": {"type": "string"}}},
        False,
    ),
    (
        "link_entities",
        "Create a typed graph edge between two entities",
        "memory_graph_relate",
        {
            "required": ["subject", "predicate", "object_entity"],
            "properties": {
                "subject": {"type": "string"},
                "predicate": {"type": "string"},
                "object_entity": {"type": "string"},
                "weight": {"type": "number"},
            },
        },
        False,
    ),
    (
        "assign_work",
        "Assign a work item to a person or agent",
        "work_update",
        {
            "required": ["work_id"],
            "properties": {
                "work_id": {"type": "string"},
                "assignee_agent": {"type": "string"},
                "assignee_email": {"type": "string"},
                "work_status": {"type": "string"},
            },
        },
        False,
    ),
    (
        "propose_strategy",
        "Propose a strategic statement",
        "memory_strategic_statement_set",
        {
            "required": ["kind", "content"],
            "properties": {
                "kind": {"type": "string", "enum": ["vision", "mission", "purpose"]},
                "content": {"type": "string"},
            },
        },
        False,
    ),
]
