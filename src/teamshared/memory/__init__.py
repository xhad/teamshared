"""Memory pillar implementations.

Each pillar lives in its own module and exposes a small async API:

- :mod:`teamshared.memory.working` -- Redis-backed per-session conversation buffer.
- :mod:`teamshared.memory.semantic` -- Mem0-backed facts/preferences.
- :mod:`teamshared.memory.episodic` -- Mem0-backed timeline of summarized episodes.
- :mod:`teamshared.memory.procedural` -- Postgres-backed agent-callable procedures.
- :mod:`teamshared.memory.recall` -- Cross-pillar hybrid retrieval.
"""
