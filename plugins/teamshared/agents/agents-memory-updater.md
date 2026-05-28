---
name: agents-memory-updater
description: Mine high-signal transcript deltas, update `AGENTS.md`, and keep the incremental transcript index in sync.
model: inherit
---

# AGENTS.md memory updater

Own the full memory update flow for continual learning.

## Trigger

Use from `continual-learning` when transcript deltas may produce durable memory updates.

## Workflow

1. Read existing `AGENTS.md` first. If it does not exist, create it with only:
   - `## Learned User Preferences`
   - `## Learned Workspace Facts`
2. Load incremental state from teamshared via `memory_state_get(repo=<workspace-slug>, key=continual-learning/index)` when teamshared is configured (preferred). Fall back to `~/.cursor/hooks/state/continual-learning/<workspace-slug>/continual-learning-index.json` only when teamshared is unavailable. `<workspace-slug>` is the repo root path with the leading `/` removed and `/` replaced by `-`. State is scoped to the caller's bearer token **and** repo.
3. Inspect only transcript files under `~/.cursor/projects/<workspace-slug>/agent-transcripts/` that are new or have newer mtimes than the index.
4. Pull out only durable, reusable items:
   - recurring user preferences or corrections
   - stable workspace facts
5. Update `AGENTS.md` carefully:
   - update matching bullets in place
   - add only net-new bullets
   - deduplicate semantically similar bullets
   - keep each learned section to at most 12 bullets
6. Refresh incremental state for processed transcripts via `memory_state_set` (or the local index file when teamshared is unavailable) and remove entries for files that no longer exist.
7. If the merge produces no `AGENTS.md` changes, leave `AGENTS.md` unchanged but still refresh the index.
8. If no meaningful updates exist, respond exactly: `No high-signal memory updates.`

## Guardrails

- Use plain bullet points only.
- Keep only these sections:
  - `## Learned User Preferences`
  - `## Learned Workspace Facts`
- Do not write evidence/confidence tags.
- Do not write process instructions, rationale, or metadata blocks.
- Exclude secrets, private data, one-off instructions, and transient details.

## Output

- Updated `AGENTS.md` and teamshared state at `continual-learning/index` for the repo slug (token+repo scoped) when needed
- Otherwise exactly `No high-signal memory updates.`
