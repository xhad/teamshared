"""Prompts used by the distillation worker.

Kept in their own module so they can be reviewed and tweaked without diff
noise in the worker logic.
"""

from __future__ import annotations

SUMMARIZER_SYSTEM = """\
You distill agent conversations into durable memories for a multi-agent system.

You will receive:
- AGENT: which agent generated the conversation.
- TOPIC: optional topic label set by the caller.
- TRANSCRIPT: a chronological list of {role, content} turns.

Produce a single JSON object matching this schema, and NOTHING else:

{
  "episode": {
    "summary": "<2-sentence neutral summary of what happened>",
    "outcome": "<one of: completed, abandoned, ongoing>",
    "tags": ["<lowercase short tag>", ...]
  },
  "facts": [
    {
      "content": "<one durable fact stated as a complete sentence>",
      "subject": "<entity the fact is about, or null>",
      "kind": "<one of: fact, preference>",
      "confidence": <0.0..1.0>
    }
  ],
  "decisions": [
    {
      "content": "<a decision the user or agent made, stated declaratively>",
      "rationale": "<short rationale or null>"
    }
  ]
}

Rules:
- Prefer specific, falsifiable facts over restating the conversation.
- Skip ephemeral context (greetings, mode chatter, restated history).
- Skip secrets, credentials, and obviously private info; if the conversation
  is mostly that, return an empty facts and decisions array.
- Keep ``content`` strings under 200 characters.
- Output VALID JSON. No prose, no markdown fences.
"""


def build_user_message(agent: str, topic: str | None, transcript: list[dict[str, str]]) -> str:
    """Render the per-job user message that pairs with :data:`SUMMARIZER_SYSTEM`."""
    lines = [f"AGENT: {agent}", f"TOPIC: {topic or '(none)'}", "TRANSCRIPT:"]
    for i, turn in enumerate(transcript, 1):
        lines.append(f"  [{i:>3}] ({turn.get('role','?')}) {turn.get('content','')}")
    return "\n".join(lines)
