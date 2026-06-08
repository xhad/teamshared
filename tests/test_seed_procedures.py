"""Sanity-check the bundled starter procedures.

These are loaded into every fresh deployment via ``teamshared seed`` so they have
to be parseable, non-empty, and uniquely named.
"""

from __future__ import annotations

from teamshared.seed.procedures import STARTER_PROCEDURES


def test_all_names_unique() -> None:
    names = [name for name, *_ in STARTER_PROCEDURES]
    assert len(names) == len(set(names))


def test_every_procedure_has_required_fields() -> None:
    for name, description, steps_md, tags in STARTER_PROCEDURES:
        assert name and name.startswith("teamshared.")
        assert description
        assert steps_md.startswith("# ")
        assert "ritual" in tags or "recall" in tags


def test_steps_reference_real_tools() -> None:
    known_tools = {
        "memory_recall",
        "memory_remember",
        "memory_session_open",
        "memory_session_append",
        "memory_session_close",
        "memory_episodes_list",
        "memory_procedure_get",
        "memory_procedure_set",
        "memory_forget",
        "memory_state_get",
        "memory_state_set",
    }
    for name, _, steps_md, _ in STARTER_PROCEDURES:
        for line in steps_md.splitlines():
            if "memory_" in line and "`memory_" in line:
                tool_refs = [
                    word.strip("`(),.")
                    for word in line.split()
                    if "`memory_" in word
                ]
                for ref in tool_refs:
                    bare = ref.replace("`", "").split("(")[0]
                    if bare:
                        assert bare in known_tools, f"{name}: unknown tool {bare}"
