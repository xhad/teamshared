"""Parse and validate a workflow's stage graph.

The stage graph is stored in a procedure's ``tool_recipe`` JSONB (the previously
unused execution-recipe hook). It is intentionally small and declarative:

    {
      "stages": [
        {"id": "triage",    "owner": "agent", "agent": "cursor",
         "playbook": "triage-pb", "advance": "auto", "on_done": "implement"},
        {"id": "implement", "owner": "agent", "playbook": "ship-pr",
         "advance": "auto", "on_done": "review"},
        {"id": "review",    "owner": "human", "advance": "manual",
         "on_approve": "done", "on_reject": "implement"}
      ],
      "loop": {"select": {"work_status": "todo"}, "until": "all_terminal",
               "max_iterations": 10}
    }

Routing targets are either another stage's ``id`` or a terminal sentinel
(``"done"`` / ``"cancelled"``) that closes the work item. The orchestrator does
not interpret free-form markdown -- it only walks this validated graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

StageOwner = Literal["agent", "human"]
AdvanceMode = Literal["auto", "manual"]

#: Routing targets that close the work item instead of moving to another stage.
TERMINAL_TARGETS: frozenset[str] = frozenset({"done", "cancelled"})

_DEFAULT_MAX_ITERATIONS = 10
_MAX_MAX_ITERATIONS = 1000
_MAX_STAGES = 50


class WorkflowDefinitionError(ValueError):
    """Raised when a stage graph is structurally invalid."""


@dataclass(frozen=True)
class Stage:
    """One node in the workflow graph."""

    id: str
    owner: StageOwner
    advance: AdvanceMode
    agent: str | None = None
    playbook: str | None = None
    playbook_version: int | None = None
    skill: str | None = None
    skill_version: int | None = None
    title: str | None = None
    on_done: str | None = None
    on_approve: str | None = None
    on_reject: str | None = None

    def next_target(self, decision: str) -> str | None:
        """Resolve the routing target for a completed step.

        ``decision`` is ``"done"`` for an agent stage (or the default human
        approval), ``"approve"`` / ``"reject"`` for a human gate. Returns the
        target stage id, a terminal sentinel, or ``None`` (treated as terminal).
        """
        if decision == "reject":
            return self.on_reject
        if decision == "approve":
            return self.on_approve if self.on_approve is not None else self.on_done
        return self.on_done


@dataclass(frozen=True)
class LoopSpec:
    """How a run selects its work-item set and when it stops iterating."""

    select: dict[str, Any]
    until: str = "all_terminal"
    max_iterations: int = _DEFAULT_MAX_ITERATIONS


@dataclass(frozen=True)
class WorkflowDefinition:
    """A validated, ordered stage graph plus optional loop spec."""

    stages: tuple[Stage, ...]
    loop: LoopSpec | None = None

    @property
    def first(self) -> Stage:
        return self.stages[0]

    def stage(self, stage_id: str) -> Stage | None:
        for stage in self.stages:
            if stage.id == stage_id:
                return stage
        return None


def _as_str(value: Any, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise WorkflowDefinitionError(f"stage field '{field}' is required")
        return None
    if not isinstance(value, str) or not value.strip():
        raise WorkflowDefinitionError(f"stage field '{field}' must be a non-empty string")
    return value.strip()


def _parse_stage(raw: Any, index: int) -> Stage:
    if not isinstance(raw, dict):
        raise WorkflowDefinitionError(f"stage #{index} must be an object")
    stage_id = _as_str(raw.get("id"), "id", required=True)
    assert stage_id is not None  # narrowed by required=True
    if stage_id in TERMINAL_TARGETS:
        raise WorkflowDefinitionError(
            f"stage id '{stage_id}' collides with a terminal sentinel"
        )

    owner = raw.get("owner", "agent")
    if owner not in ("agent", "human"):
        raise WorkflowDefinitionError(
            f"stage '{stage_id}' owner must be 'agent' or 'human'"
        )

    advance = raw.get("advance")
    if advance is None:
        advance = "auto" if owner == "agent" else "manual"
    if advance not in ("auto", "manual"):
        raise WorkflowDefinitionError(
            f"stage '{stage_id}' advance must be 'auto' or 'manual'"
        )

    version_raw = raw.get("playbook_version")
    if version_raw is not None and not isinstance(version_raw, int):
        raise WorkflowDefinitionError(
            f"stage '{stage_id}' playbook_version must be an integer"
        )

    skill_version_raw = raw.get("skill_version")
    if skill_version_raw is not None and not isinstance(skill_version_raw, int):
        raise WorkflowDefinitionError(
            f"stage '{stage_id}' skill_version must be an integer"
        )

    return Stage(
        id=stage_id,
        owner=owner,
        advance=advance,  # type: ignore[arg-type]
        agent=_as_str(raw.get("agent"), "agent"),
        playbook=_as_str(raw.get("playbook"), "playbook"),
        playbook_version=version_raw,
        skill=_as_str(raw.get("skill"), "skill"),
        skill_version=skill_version_raw,
        title=_as_str(raw.get("title"), "title"),
        on_done=_as_str(raw.get("on_done"), "on_done"),
        on_approve=_as_str(raw.get("on_approve"), "on_approve"),
        on_reject=_as_str(raw.get("on_reject"), "on_reject"),
    )


def _parse_loop(raw: Any) -> LoopSpec | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise WorkflowDefinitionError("'loop' must be an object")
    select = raw.get("select", {})
    if not isinstance(select, dict):
        raise WorkflowDefinitionError("'loop.select' must be an object")
    until = raw.get("until", "all_terminal")
    if until not in ("all_terminal",):
        raise WorkflowDefinitionError("'loop.until' must be 'all_terminal'")
    max_iterations = raw.get("max_iterations", _DEFAULT_MAX_ITERATIONS)
    if not isinstance(max_iterations, int) or not 1 <= max_iterations <= _MAX_MAX_ITERATIONS:
        raise WorkflowDefinitionError(
            f"'loop.max_iterations' must be an integer in [1, {_MAX_MAX_ITERATIONS}]"
        )
    return LoopSpec(select=select, until=until, max_iterations=max_iterations)


def parse_definition(tool_recipe: Any) -> WorkflowDefinition:
    """Validate a ``tool_recipe`` payload into a :class:`WorkflowDefinition`.

    Raises :class:`WorkflowDefinitionError` with a human-readable message on any
    structural problem (unknown routing target, duplicate id, empty graph, ...).
    """
    if not isinstance(tool_recipe, dict):
        raise WorkflowDefinitionError("workflow definition must be an object")
    raw_stages = tool_recipe.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        raise WorkflowDefinitionError("workflow must define a non-empty 'stages' list")
    if len(raw_stages) > _MAX_STAGES:
        raise WorkflowDefinitionError(f"workflow may not exceed {_MAX_STAGES} stages")

    stages = tuple(_parse_stage(raw, i) for i, raw in enumerate(raw_stages))

    seen: set[str] = set()
    for stage in stages:
        if stage.id in seen:
            raise WorkflowDefinitionError(f"duplicate stage id '{stage.id}'")
        seen.add(stage.id)

    valid_targets = seen | TERMINAL_TARGETS
    for stage in stages:
        for field in ("on_done", "on_approve", "on_reject"):
            target = getattr(stage, field)
            if target is not None and target not in valid_targets:
                raise WorkflowDefinitionError(
                    f"stage '{stage.id}' {field} -> '{target}' is not a known stage"
                )
        if stage.owner == "human" and stage.on_approve is None and stage.on_done is None:
            raise WorkflowDefinitionError(
                f"human stage '{stage.id}' needs an 'on_approve' (or 'on_done') target"
            )

    loop = _parse_loop(tool_recipe.get("loop"))
    return WorkflowDefinition(stages=stages, loop=loop)
