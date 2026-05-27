"""Memory pillar implementations.

Each pillar lives in its own module and exposes a small async API:

- :mod:`sptx.memory.working` -- Redis-backed per-session conversation buffer.
- :mod:`sptx.memory.semantic` -- Mem0-backed facts/preferences.
- :mod:`sptx.memory.episodic` -- Mem0-backed timeline of summarized episodes.
- :mod:`sptx.memory.procedural` -- Postgres-backed agent-callable procedures.
- :mod:`sptx.memory.recall` -- Cross-pillar hybrid retrieval.
"""
