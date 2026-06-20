# teamshared (Cursor plugin)

One plugin for shared team memory in Cursor: MCP wiring, recall-first rules,
AGENTS.md continual learning, and copy-paste snippets for other clients.

| Component | Purpose |
|---|---|
| `rules/teamshared.mdc` | Recall-first protocol, `repo=` + `github=` code scope, console pointer (`alwaysApply`) |
| `install/` | Harness templates served at `/install/assets/*` by `install.sh` (single source of truth) |
| `clients/` | Copy-paste protocol + extended MCP examples for manual setup |
| `skills/teamshared/` | Memory tool chooser + session workflow |
| `skills/continual-learning/` | Orchestrates AGENTS.md updates from transcripts |
| `hooks/` | Continual-learning stop hook only |
| `agents/agents-memory-updater.md` | Mines transcripts and updates `AGENTS.md` |
| `clients/` | Snippets for Hermes, Claude Desktop, and plain-text protocol |

The continual-learning hook is based on [Cursor's continual-learning plugin](https://github.com/cursor/plugins) (MIT), modified to store cadence and transcript index on teamshared.

## Install

### From marketplace (recommended)

1. **Settings → Plugins → Add marketplace** → `https://github.com/xhad/teamshared`
2. Run **`/add-plugin teamshared`** or enable it under Settings → Plugins
3. Add the MCP server to `~/.cursor/mcp.json` (below) and reload

See [MARKETPLACE.md](MARKETPLACE.md) for publish/submission checklist.

### From this repo (symlink)

```bash
ln -sf "$(pwd)/plugins/teamshared" ~/.cursor/plugins/local/teamshared
```

## Setup

1. **teamshared server + bearer token** — sign in to the web console at
   `<server>/app` (e.g. https://teamshared.com/app) with your email and a
   one-time passcode, then mint a key under **API Keys** (`tsk_…`). The
   the console **API Keys** page (`/app/keys`) works too, or ask an admin for an invite link. First sign-in
   is self-service: any email gets its own org, and you can create/switch orgs and
   add teammates (People → add member) from the console. The bearer token below is
   what Cursor's MCP client uses.
2. **MCP server config** — put the URL and bearer token **directly** in `~/.cursor/mcp.json`
   (no environment variables). `install.sh` writes this for you;
   to do it manually, merge:

```json
{
  "mcpServers": {
    "teamshared": {
      "url": "https://teamshared.com/mcp",
      "headers": { "Authorization": "Bearer tsk_..." }
    }
  }
}
```

3. **[Bun](https://bun.sh)** on PATH for the continual-learning stop hook (optional if you skip continual learning).
4. **Developer: Reload Window** — confirm **Settings → MCP** shows `teamshared` enabled.

Do not install the upstream Cursor `continual-learning` marketplace plugin — this bundle replaces it with teamshared state storage.

## Context compression (MCP)

Compression is **MCP-first** — no Cursor hooks required for the context pipeline.

| Surface | When to use |
|---|---|
| **MCP middleware** | Automatic on every teamshared tool response (`memory_recall`, etc.) |
| **`context_prepare`** | Before a model turn: session log + compress history + enrich org memory |
| **`context_normalize`** | After Shell/Grep/Read or other non-teamshared tools return large output |
| **`context_compress`** / **`context_retrieve`** | Manual message-list compression and CCR retrieval |

See [`docs/context-compression.md`](../../docs/context-compression.md) for the full model, CCR, and configuration. Toggle the prepare pipeline with `TEAMSHARED_LLM_PREPARE_ENABLED` (default on).

There is **no** OpenAI gateway URL to configure — Cursor keeps talking to its normal model provider.

## What you get

- **MCP tools**: `memory_recall`, `memory_remember`, `memory_session_*`, etc.
- **Rule**: injects the recall-first protocol on every agent turn, and points
  teammates to the web console (`/app`) for human actions.
- **Web console** (`<server>/app`): self-service OTP sign-in, multi-tenant orgs
  (own org on first login, create/switch, add members), a browsable memory wiki,
  and management of agents and API keys.
- **Continual learning**: on cadence, updates `AGENTS.md` from chat transcripts;
  state keys `continual-learning/cadence` and `continual-learning/index` on
  teamshared (token + repo scoped), with local fallback under
  `~/.cursor/hooks/state/continual-learning/<workspace-slug>/`.
- **Session logging**: the `teamshared.mdc` rule covers `memory_session_*` on every chat; use `context_prepare` when you also want compression and enrichment in one call.

## Other clients

See [`clients/`](clients/) for Hermes, Claude Desktop, and protocol markdown.

## License

MIT — see [LICENSE](LICENSE). Continual-learning portions derived from Cursor's plugin ([LICENSE-continual-learning](LICENSE-continual-learning)).
