"""Background worker agents: async, single-shot execution of Work Board tasks.

The pieces:

* :mod:`teamshared.agents.runs` -- ``AgentRunStore``, org-scoped CRUD + a
  DB-guarded lease over ``agent_runs`` / ``agent_trace_events`` /
  ``agent_model_calls``.
* :mod:`teamshared.agents.service` -- ``AgentRunService``, the lifecycle facade
  (assign / enqueue / cancel / retry) that also drops work-comment events.
* :mod:`teamshared.agents.runner` -- ``run_agent``, the single-shot reasoning
  step (context pack + teamshared.mdc + playbook -> OpenRouter -> trace).
* :mod:`teamshared.agents.worker` -- the long-running consumer process.
"""
