"""Playbook composition: skill collections stored in ``tool_recipe.skills``.

A playbook is an ordered list of skills (plus optional intro markdown in
``steps_md``). At runtime :func:`expand_playbook_skills` inlines each skill's
``body_md`` so agents execute them in sequence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from teamshared.memory.skills import OrgSkillStore


@dataclass(frozen=True)
class SkillRef:
    """A named skill reference, optionally pinned to a version."""

    name: str
    version: int | None = None


def is_workflow_recipe(tool_recipe: Any) -> bool:
    """True when ``tool_recipe`` defines workflow stages (not a skill playbook)."""
    return isinstance(tool_recipe, dict) and bool(tool_recipe.get("stages"))


def skill_names_from_recipe(tool_recipe: Any) -> list[str]:
    """Ordered skill names referenced by a playbook's ``tool_recipe``."""
    return [ref.name for ref in parse_skill_refs(tool_recipe)]


def build_skill_recipe(
    skill_names: list[str],
    *,
    max_iterations: int | None = None,
) -> dict[str, Any]:
    """Build a playbook ``tool_recipe`` from an ordered skill name list."""
    names = [n.strip() for n in skill_names if isinstance(n, str) and n.strip()]
    if not names:
        raise ValueError("playbook requires at least one skill")
    recipe: dict[str, Any] = {"skills": names}
    if max_iterations is not None and max_iterations > 0:
        recipe["loop"] = {"max_iterations": max_iterations}
    return recipe


def parse_skill_refs(tool_recipe: Any) -> list[SkillRef]:
    """Extract skill references from a procedure's ``tool_recipe``.

    Supported shapes::

        {"skills": ["ship-pr", "debug-ci"]}
        {"skills": [{"name": "ship-pr", "version": 2}]}
        {"skill_versions": {"ship-pr": 2}}  # optional version pins
    """
    if not isinstance(tool_recipe, dict):
        return []
    raw = tool_recipe.get("skills")
    if not raw:
        return []
    version_pins: dict[str, int] = {}
    pins = tool_recipe.get("skill_versions")
    if isinstance(pins, dict):
        for key, val in pins.items():
            if isinstance(key, str) and isinstance(val, int):
                version_pins[key.strip()] = val

    refs: list[SkillRef] = []
    if not isinstance(raw, list):
        return refs
    for item in raw:
        if isinstance(item, str) and item.strip():
            name = item.strip()
            refs.append(SkillRef(name=name, version=version_pins.get(name)))
        elif isinstance(item, dict):
            name_val = item.get("name")
            if not isinstance(name_val, str) or not name_val.strip():
                continue
            name = name_val.strip()
            ver = item.get("version")
            version = ver if isinstance(ver, int) else version_pins.get(name)
            refs.append(SkillRef(name=name, version=version))
    return refs


async def expand_playbook_skills(
    store: OrgSkillStore,
    org_id: UUID,
    *,
    steps_md: str,
    tool_recipe: dict[str, Any] | None,
) -> str:
    """Append resolved skill bodies after the playbook's own ``steps_md``.

    Missing or inactive skills are skipped with a short placeholder so the
    agent knows composition failed partially rather than silently.
    """
    refs = parse_skill_refs(tool_recipe)
    if not refs:
        return steps_md

    sections = [steps_md.rstrip()] if steps_md and steps_md.strip() else []
    sections.append("## Composed skills")
    for ref in refs:
        skill = await store.get_skill(org_id, ref.name, ref.version)
        if skill is None:
            pin = f" v{ref.version}" if ref.version else ""
            sections.append(f"### Skill: {ref.name}{pin}\n\n_(unavailable)_")
            continue
        ver = skill.get("version")
        sections.append(
            f"### Skill: {skill['name']} (v{ver})\n\n{skill.get('body_md') or ''}".rstrip()
        )
    return "\n\n".join(sections).strip()
