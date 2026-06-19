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


CURATOR_SYSTEM = """\
You maintain a team knowledge base. Given everything the team's agents have
recorded about ONE subject, write a single canonical wiki article.

You will receive:
- SUBJECT: the topic of the page.
- FACTS: durable statements about the subject (each with kind, confidence, date).
- EPISODES: recent timestamped events touching the subject.

Produce a single JSON object matching this schema, and NOTHING else:

{
  "title": "<short human title for the page>",
  "body_md": "<the article as GitHub-flavored markdown>"
}

Rules:
- Synthesize; do NOT just list the inputs. Merge duplicates and group related
  points under markdown headings (##) with bullet points.
- When facts conflict, prefer the most recent and highest-confidence one; you may
  note that something changed, but state the current truth plainly.
- Only use information present in FACTS/EPISODES. Never invent details.
- Keep it tight and scannable. No preamble, no "as an AI", no fabricated sources.
- ``body_md`` is markdown ONLY (no raw HTML). Output VALID JSON, no code fences.
"""


def build_curator_message(
    subject: str,
    facts: list[dict[str, object]],
    episodes: list[dict[str, object]],
) -> str:
    """Render the per-subject user message that pairs with :data:`CURATOR_SYSTEM`."""
    lines = [f"SUBJECT: {subject}", "FACTS:"]
    if facts:
        for f in facts:
            kind = f.get("kind") or "fact"
            conf = f.get("confidence")
            conf_s = f" conf={conf}" if conf is not None else ""
            date = str(f.get("created_at") or "")[:10]
            lines.append(f"  - ({kind}{conf_s} {date}) {f.get('content', '')}")
    else:
        lines.append("  (none)")
    lines.append("EPISODES:")
    if episodes:
        for e in episodes:
            date = str(e.get("created_at") or "")[:10]
            lines.append(f"  - [{date}] {e.get('content', '')}")
    else:
        lines.append("  (none)")
    return "\n".join(lines)


THINKER_SYSTEM = """\
You answer questions using ONLY the team memory excerpts provided.

You will receive:
- QUERY: the user's question.
- SOURCES: numbered memory excerpts, each with [id], pillar, and content.

Produce a single JSON object matching this schema, and NOTHING else:

{
  "answer_md": "<synthesized answer as GitHub-flavored markdown with inline [n] citation markers>",
  "citations": [
    {"index": <1-based source number>, "memory_id": "<id from source>", "claim": "<short cited claim>"}
  ]
}

Rules:
- Write a direct, useful answer — not a list of sources to read.
- Every factual claim must have at least one [n] citation marker matching a source number.
- Use ONLY information in SOURCES. Do not invent facts.
- If sources conflict, state the conflict plainly and prefer the most recent.
- If sources are insufficient, say what is missing in the answer itself.
- Keep ``answer_md`` under 800 words. Output VALID JSON, no markdown fences.
"""


def build_thinker_message(
    query: str,
    sources: list[dict[str, str]],
    gaps: list[dict[str, str]],
) -> str:
    """Render the per-query user message for :data:`THINKER_SYSTEM`."""
    lines = [f"QUERY: {query}", "SOURCES:"]
    if sources:
        for i, src in enumerate(sources, 1):
            lines.append(
                f"  [{i}] id={src.get('id','?')} pillar={src.get('pillar','?')} "
                f"agent={src.get('agent') or 'unknown'} "
                f"date={src.get('date') or 'unknown'}"
            )
            lines.append(f"      {src.get('content', '')}")
    else:
        lines.append("  (no relevant memory found)")
    lines.append("GAPS (pre-detected; mention in answer if relevant):")
    if gaps:
        for g in gaps:
            lines.append(f"  - ({g.get('kind','?')}) {g.get('claim','')}")
    else:
        lines.append("  (none)")
    return "\n".join(lines)
