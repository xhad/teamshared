"""Tests for procedure → skill migration helpers."""

from __future__ import annotations

from teamshared.migrate.procedures_to_skills import classify_procedure, tool_recipe_to_hints


def test_classify_atomic() -> None:
    assert classify_procedure(None) == "atomic"
    assert classify_procedure({"tools": ["memory_recall"]}) == "atomic"


def test_classify_workflow() -> None:
    assert classify_procedure({"stages": [{"id": "triage"}]}) == "workflow"


def test_classify_composed() -> None:
    assert classify_procedure({"skills": ["ship-pr"]}) == "composed"


def test_tool_recipe_to_hints_skips_workflow() -> None:
    assert tool_recipe_to_hints({"stages": [{"id": "triage"}]}) is None


def test_tool_recipe_to_hints_copies_atomic() -> None:
    recipe = {"tools": ["memory_recall"]}
    assert tool_recipe_to_hints(recipe) == recipe
