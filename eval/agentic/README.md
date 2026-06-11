# Agentic A/B evaluation

Measures whether teamshared memory makes agentic coding workflows better, not
just whether recall works (that's `eval/golden.yaml`). Each task runs N fresh
Cursor agents per arm via the Cursor SDK against this repo checkout:

- **memory** arm: teamshared MCP attached + a one-line preamble telling the
  agent to `memory_recall` first.
- **baseline** arm: identical agent, no memory.

The only variable is memory. Scored on answer correctness (substring groups in
`tasks.yaml`), wall time, assistant turns, and tool calls. Control tasks
(`control: true`) are ones memory should *not* help with — if the memory arm
wins those, the harness is biased.

## Setup

```bash
pip install 'teamshared[eval-agentic]'
export CURSOR_API_KEY=cursor_...           # cursor.com/dashboard -> Integrations
export TEAMSHARED_EVAL_URL=https://teamshared.com/mcp/
export TEAMSHARED_EVAL_TOKEN=tsk_...       # org-scoped API key
```

The memory arm is only meaningful if the org's brain is seeded (real distilled
sessions, repo facts). An empty teamshared shows zero benefit by construction.

## Run

```bash
python eval/agentic/runner.py --trials 5            # full matrix
python eval/agentic/runner.py --arms baseline       # one arm only
python eval/agentic/runner.py --tasks integration-tests recall-score-flip
make eval-agentic                                    # trials=3 default
```

Per-trial records stream to `eval/agentic/results/run-<ts>.jsonl`; a markdown
summary table prints at the end. Re-aggregate later (or merge runs) with:

```bash
python eval/agentic/runner.py --report 'eval/agentic/results/run-*.jsonl'
```

## Reading the results

- **Success rate** alone undersells memory: the baseline can usually dig the
  same facts out of the repo. The honest wins are fewer turns/tool calls and
  lower wall time on the tribal-knowledge tasks, with parity on controls.
- A *worse* memory arm is signal too — usually stale or poisoned memories, or
  protocol overhead exceeding recall benefit on trivial tasks.
- Trials are noisy; don't conclude anything from n < 5 per cell.

## Caveats

- Agents are prompted not to modify files, but local runs are not sandboxed;
  run on a clean checkout and `git status` afterwards.
- Scoring is substring-based: cheap and deterministic, but it grades recall of
  facts, not solution quality. For code-writing tasks, extend `tasks.yaml`
  with a checker command (future work).
