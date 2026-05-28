# teamshared (Cursor plugin)

One plugin for shared team memory in Cursor: MCP wiring, recall-first rules,
AGENTS.md continual learning, and copy-paste snippets for other clients.

| Component | Purpose |
|---|---|
| `mcp.json` | Wires `teamshared` via `TEAMSHARED_URL` + `TEAMSHARED_TOKEN` |
| `rules/teamshared.mdc` | Recall-first protocol (`alwaysApply`) |
| `skills/teamshared/` | Memory tool chooser + session workflow |
| `skills/continual-learning/` | Orchestrates AGENTS.md updates from transcripts |
| `hooks/` | Stop hook — cadence gating + teamshared-backed state |
| `agents/agents-memory-updater.md` | Mines transcripts and updates `AGENTS.md` |
| `clients/` | Snippets for Hermes, Claude Desktop, and plain-text protocol |

The continual-learning hook is based on [Cursor's continual-learning plugin](https://github.com/cursor/plugins) (MIT), modified to store cadence and transcript index on teamshared.

## Prerequisites

1. A running teamshared server and bearer token (see main [README](../README.md)).
2. **Bun** on PATH for continual-learning hooks (`bun --version`).
3. Environment variables before launching Cursor:

```bash
export TEAMSHARED_URL=https://actx.teamshared.com/mcp
export TEAMSHARED_TOKEN=teamshared_...
```

## Install

```bash
ln -sf "$(pwd)/plugins/teamshared" ~/.cursor/plugins/local/teamshared
```

Reload Cursor (**Developer: Reload Window**). Confirm under **Settings → Plugins** that
**teamshared** appears, and under **Settings → MCP** that the server is enabled.

Do not install the upstream Cursor `continual-learning` marketplace plugin — this
bundle replaces it with teamshared state storage.

## What you get

- **MCP tools**: `memory_recall`, `memory_remember`, `memory_session_*`, etc.
- **Rule**: injects the recall-first protocol on every agent turn.
- **Continual learning**: on cadence, updates `AGENTS.md` from chat transcripts;
  state keys `continual-learning/cadence` and `continual-learning/index` on
  teamshared (token + repo scoped), with local fallback under
  `~/.cursor/hooks/state/continual-learning/<workspace-slug>/`.

## Other clients

See [`clients/`](clients/) for Hermes, Claude Desktop, and protocol markdown.

## License

MIT — teamshared components by Sapien; continual-learning hook derived from Cursor's plugin (see [LICENSE-continual-learning](LICENSE-continual-learning)).
