"""Built-in starter procedures.

Each entry is a tuple of ``(name, description, steps_md, tags)``. They cover
the most common cross-agent rituals: starting a session, capturing decisions,
and querying memory.
"""

from __future__ import annotations

STARTER_PROCEDURES: list[tuple[str, str, str, list[str]]] = [
    (
        "teamshared.start-of-task",
        "Standard preamble at the start of any non-trivial task.",
        """\
# Start-of-task ritual

1. Call `memory_session_open(topic=<task name>)` and remember the returned `session_id`.
2. Call `memory_recall(query=<task description>, k=8)` to surface prior context.
3. Append a one-line summary of the user's goal via
   `memory_session_append(session_id, role="system", content=<goal>)`.

Why: every later turn benefits from the same retrieved context, and the
distiller can do its job at session close.""",
        ["ritual", "session"],
    ),
    (
        "teamshared.end-of-task",
        "Standard postamble at the end of any non-trivial task.",
        """\
# End-of-task ritual

1. Append a short status note via `memory_session_append(session_id,
   role="system", content="status: <done|abandoned|paused>")`.
2. Call `memory_session_close(session_id, distill=true)`.
3. (Optional) `memory_remember` any specific facts you want the distiller not
   to miss (e.g. "user prefers tabs over spaces").

Why: distillation runs on the closed session and writes durable facts +
episodes that other agents will see in their next `memory_recall`.""",
        ["ritual", "session"],
    ),
    (
        "teamshared.capture-decision",
        "Persist a decision so other agents see the same answer next time.",
        """\
# Capture a decision

1. Phrase the decision declaratively, e.g.
   "We will deploy via GitHub Actions, not Vercel."
2. Call `memory_remember(content=<decision>, kind="fact",
   tags=["decision", <area>])`.
3. (Optional) Add the rationale as a second fact tagged `rationale`.

Why: cross-agent consistency. Future tasks from any agent will retrieve this
in `memory_recall` if the query is relevant.""",
        ["ritual", "decisions"],
    ),
    (
        "teamshared.capture-preference",
        "Persist a stable user preference.",
        """\
# Capture a user preference

1. Phrase as a preference: "User prefers ___ over ___."
2. Call `memory_remember(content=<preference>, kind="preference",
   subject="user", tags=["preference"])`.

Why: preferences are the most-recalled facts; tagging them lets the recall
weighting push them up.""",
        ["ritual", "preferences"],
    ),
    (
        "teamshared.search-before-asking",
        "Before asking the user a clarifying question, search memory first.",
        """\
# Search before asking

1. Identify the gap you'd ask the user about.
2. Call `memory_recall(query=<gap phrased as a question>, k=5)`.
3. If a relevant fact/preference exists, use it and skip the question.
4. If nothing relevant, ask the user, then immediately persist the answer via
   `memory_remember`.

Why: respecting prior answers is the single biggest UX win of a shared
memory.""",
        ["ritual", "recall"],
    ),
]
