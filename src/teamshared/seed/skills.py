"""Built-in starter skills (atomic instruction building blocks).

These were historically stored as procedures/playbooks before the skills pillar
existed. Each entry is ``(name, description, body_md, tags)``.
"""

from __future__ import annotations

from teamshared.seed.procedures import STARTER_PROCEDURES

STARTER_SKILLS: list[tuple[str, str, str, list[str]]] = [
    (name, description, steps_md, tags)
    for name, description, steps_md, tags in STARTER_PROCEDURES
]
