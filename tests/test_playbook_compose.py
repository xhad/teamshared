"""Skill reference parsing and playbook expansion."""

from __future__ import annotations

from teamshared.playbook.compose import SkillRef, expand_playbook_skills, parse_skill_refs


def test_parse_skill_refs_string_names() -> None:
    refs = parse_skill_refs({"skills": ["ship-pr", "debug-ci"]})
    assert refs == [SkillRef("ship-pr"), SkillRef("debug-ci")]


def test_parse_skill_refs_objects_and_pins() -> None:
    recipe = {
        "skills": [{"name": "ship-pr", "version": 2}, "lint"],
        "skill_versions": {"lint": 3},
    }
    refs = parse_skill_refs(recipe)
    assert refs[0] == SkillRef("ship-pr", 2)
    assert refs[1] == SkillRef("lint", 3)


def test_parse_skill_refs_empty_when_missing() -> None:
    assert parse_skill_refs(None) == []
    assert parse_skill_refs({}) == []
    assert parse_skill_refs({"stages": []}) == []


async def test_expand_playbook_skills_inlines_bodies() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from uuid import UUID

    store = MagicMock()
    store.get_skill = AsyncMock(
        side_effect=[
            {"name": "lint", "version": 1, "body_md": "Run ruff."},
            {"name": "ship", "version": 2, "body_md": "Open a PR."},
        ]
    )
    out = await expand_playbook_skills(
        store,
        UUID("00000000-0000-0000-0000-000000000001"),
        steps_md="# Playbook\n\nLoop through skills.",
        tool_recipe={"skills": ["lint", "ship"]},
    )
    assert "Loop through skills." in out
    assert "### Skill: lint (v1)" in out
    assert "Run ruff." in out
    assert "### Skill: ship (v2)" in out
    assert "Open a PR." in out


async def test_expand_playbook_skills_placeholder_when_missing() -> None:
    from unittest.mock import AsyncMock, MagicMock
    from uuid import UUID

    store = MagicMock()
    store.get_skill = AsyncMock(return_value=None)
    out = await expand_playbook_skills(
        store,
        UUID("00000000-0000-0000-0000-000000000001"),
        steps_md="",
        tool_recipe={"skills": ["missing"]},
    )
    assert "### Skill: missing" in out
    assert "_(unavailable)_" in out
