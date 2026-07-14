# Conversation replay — token cost A/B

Measure whether **teamshared costs more tokens** than a baseline agent session
that keeps raw message history (including fat Shell/Grep/MCP tool output).

This is an **offline replay** of a YAML transcript — you do not need to burn
tokens re-running the whole chat in Cursor unless you opt into `--agent`.

## What it compares

| Arm | What it models |
|-----|----------------|
| **baseline** | Raw OpenAI-style messages replayed turn-by-turn. Every tool dump stays in context. |
| **compress** | `context_normalize` + `context_compress` (CCR). No memory enrichment. |
| **full** | Above + budgeted org-memory pack from `POST /llm/prepare` (HTTP only). |

Two cost metrics:

1. **Final-turn tokens** — context size on the last turn (what matters if you only call the model once at the end).
2. **Session cumulative tokens** — sum of context size after *each* turn (what matters if the LLM runs every step). **Use this to answer “is teamshared more expensive overall?”**

Early turns often show **negative** savings: enrichment injects ~800–900 tokens before
fat tool output arrives. Sessions with large tool JSON/logs are where teamshared
typically wins (often 85–95% session savings in bundled fixtures).

## Quick start in Cursor

### 1. Install dev deps

```bash
pip install -e '.[dev]'
```

For live Cursor agent arms (`--agent`):

```bash
pip install -e '.[eval-agentic]'
export CURSOR_API_KEY=cursor_...
```

### 2. Offline cost check (no server)

```bash
python eval/conversation_replay/compare_cost.py eval/conversation_replay.example.yaml
```

Or the bundled teamshared debugging thread:

```bash
python eval/conversation_replay/compare_cost.py eval/conversation_replay.teamshared.yaml
```

### 3. Full stack (compression + enrichment)

Point at your teamshared server (production or local `teamshared serve`):

```bash
export TEAMSHARED_EVAL_URL=https://teamshared.com/mcp/
export TEAMSHARED_EVAL_TOKEN=tsk_...    # mint at https://teamshared.com/app/keys

python eval/conversation_replay/compare_cost.py --http eval/conversation_replay.teamshared.yaml
```

Local server example:

```bash
export TEAMSHARED_EVAL_URL=http://127.0.0.1:8000/mcp/
export TEAMSHARED_EVAL_TOKEN=tsk_...
```

### 4. Visual dashboard

```bash
make eval-conversation-report-http   # needs TEAMSHARED_EVAL_* 
open eval/conversation_replay/results/dashboard.html
```

Or offline:

```bash
make eval-conversation-report
open eval/conversation_replay/results/dashboard.html
```

### 5. Replay *your* Cursor session

1. Copy `eval/conversation_replay/cursor-session.yaml` or edit it in place.
2. Paste turns from your chat (`user`, `assistant`, `tool` blocks — see example fixtures).
3. Set `repo:` to your workspace slug (`Users-chad-code-teamshared` style).
4. Run `compare_cost.py` as above.

## USD estimates

Set input price per million tokens (default `$3`):

```bash
export TEAMSHARED_EVAL_USD_PER_MTOK=3.0
```

Session USD is **input-only** and approximate — it does not model output tokens or
MCP tool-call API charges.

## Live LLM session (`--agent`)

Runs the **last user message** through Cursor SDK twice:

- **baseline** — no teamshared MCP
- **memory** — teamshared MCP attached; prompted to `memory_recall` first

```bash
export CURSOR_API_KEY=cursor_...
export TEAMSHARED_EVAL_URL=https://teamshared.com/mcp/
export TEAMSHARED_EVAL_TOKEN=tsk_...

python eval/conversation_replay/compare_cost.py \
  --http --agent eval/conversation_replay.example.yaml
```

This scores answer quality (`agent_expect` in YAML) but does **not** yet meter
Cursor billing tokens — use replay metrics for cost, `--agent` for quality.

## Fixture schema

```yaml
name: my-session
repo: Users-you-code-yourrepo      # optional; scopes enrichment
github: owner/repo                 # optional

recall:                            # http mode: live memory_recall probe
  query: short keywords
  expect_any: [needle1, needle2]

context_expect_any: [needle]       # http mode: must appear in enriched context

turns:
  - user: "question"
  - assistant: "plan"
  - tool:
      name: Shell
      generate: grep_json_500      # synthetic fat JSON
  - tool:
      name: MCP:memory_recall
      generate: memory_recall_fat
  - tool:
      name: Read
      output: |
        pasted real tool output
```

Generators: `grep_json_300`, `grep_json_500`, `memory_recall_fat`, `error_log_200`.

## Makefile targets

| Target | Description |
|--------|-------------|
| `make eval-conversation` | Offline replay of example fixture |
| `make eval-conversation-report` | Example + teamshared fixtures → dashboard |
| `make eval-conversation-report-http` | Same, against live server |
| `make eval-conversation-cost` | `compare_cost.py` on bundled fixtures |

## Related evals

| Path | Purpose |
|------|---------|
| `eval/golden.yaml` + `eval/run.py` | Recall quality (did memory return the right fact?) |
| `eval/agentic/` | Cursor SDK A/B task success rate (not token cost) |

## Interpreting results

| Signal | Meaning |
|--------|---------|
| Session cumulative **lower** with teamshared | Teamshared is cheaper for this transcript shape. |
| Early turns negative, late turns positive | Normal — enrichment upfront, compression pays off after fat tools. |
| `full` only slightly above `compress` | Enrichment is cheap vs tool compression wins. |
| `full` >> `compress` | Lower `token_budget` on `/llm/prepare` or skip enrich on tool-heavy turns. |
| `recall` FAIL | Memory pack missing expected facts — quality issue, not cost. |

Bundled reference run (HTTP, 2026-07-12): `integration-test-thread` final context
16,058 → 1,522 tokens (~90% reduction); `teamshared-tribal-knowledge-debug`
23,991 → 2,123 (~91%).
