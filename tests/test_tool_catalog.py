"""MCP tool catalog and recall defaults."""

from __future__ import annotations

from teamshared.memory.types import DEFAULT_RECALL_SCOPES
from teamshared.server.tool_catalog import list_tools


def test_default_recall_scopes_include_skill() -> None:
    assert "skill" in DEFAULT_RECALL_SCOPES
    assert "procedural" in DEFAULT_RECALL_SCOPES


def test_default_recall_scopes_exclude_working() -> None:
    """Open-session tool turns must not crowd default recall / think."""
    assert "working" not in DEFAULT_RECALL_SCOPES


def test_catalog_groups_memory_tools() -> None:
    out = list_tools(scope="memory", tier="core")
    names = {e["name"] for group in out["groups"].values() for e in group}
    assert "memory_recall" in names
    assert "memory_skill_get" in names
    assert "memory_skill_set" in names
    assert "memory_playbook_get" in names
    assert "memory_playbook_set" in names
    assert "memory_tools_catalog" in names
    assert "integration_list" in names
    assert "integration_search" in names
    assert "integration_read" in names
    assert "integration_send" in names


def test_catalog_includes_tool_recipe_shapes() -> None:
    out = list_tools()
    assert "skills_compose" in out["tool_recipe_shapes"]
