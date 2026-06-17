"""Procedural-loop workflow engine.

A workflow definition is a versioned procedure whose ``tool_recipe`` carries a
validated stage graph (:mod:`teamshared.workflow.definition`). A workflow run
(:mod:`teamshared.workflow.runs`) walks a set of work items through those stages;
the :class:`~teamshared.workflow.orchestrator.WorkflowOrchestrator` advances
agent stages by reusing the ``agent_runs`` executor and gates human stages until
a teammate advances them.
"""

from __future__ import annotations

from teamshared.workflow.definition import (
    TERMINAL_TARGETS,
    LoopSpec,
    Stage,
    WorkflowDefinition,
    WorkflowDefinitionError,
    parse_definition,
)

__all__ = [
    "TERMINAL_TARGETS",
    "LoopSpec",
    "Stage",
    "WorkflowDefinition",
    "WorkflowDefinitionError",
    "parse_definition",
]
