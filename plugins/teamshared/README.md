# teamshared (Cursor plugin)

One plugin for shared team memory in Cursor: MCP wiring, recall-first rules,
AGENTS.md continual learning, and copy-paste snippets for other clients.

| Component | Purpose |
|---|---|
| `rules/teamshared.mdc` | Recall-first protocol, `repo=` + `github=` code scope, console pointer (`alwaysApply`) |
| `skills/teamshared/` | Memory tool chooser + session workflow |
| `skills/continual-learning/` | Orchestrates AGENTS.md updates from transcripts |
| `hooks/` | Stop hook — cadence gating + teamshared-backed state |
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
   `/get-token` page works too, or ask an admin for an invite link. First sign-in
   is self-service: any email gets its own org, and you can create/switch orgs and
   add teammates (People → add member) from the console. The bearer token below is
   what Cursor's MCP client uses.
2. **MCP server config** — put the URL and bearer token **directly** in `~/.cursor/mcp.json`
   (no environment variables). The `/get-token` page and `install.sh` write this for you;
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

3. **[Bun](https://bun.sh)** on PATH for continual-learning hooks.
4. **Developer: Reload Window** — confirm **Settings → MCP** shows `teamshared` enabled.

Do not install the upstream Cursor `continual-learning` marketplace plugin — this bundle replaces it with teamshared state storage.

## What you get

- **MCP tools**: `memory_recall`, `memory_remember`, `memory_session_*`, etc.
- **Rule**: injects the recall-first protocol on every agent turn, and points
  teammates to the web console (`/app`) for human actions.
- **Web console** (`<server>/app`): self-service OTP sign-in, multi-tenant orgs
  (own org on first login, create/switch, add members), a browsable memory wiki,
  and management of agents, API keys, approvals, and capture consent.
- **Continual learning**: on cadence, updates `AGENTS.md` from chat transcripts;
  state keys `continual-learning/cadence` and `continual-learning/index` on
  teamshared (token + repo scoped), with local fallback under
  `~/.cursor/hooks/state/continual-learning/<workspace-slug>/`.

## Other clients

See [`clients/`](clients/) for Hermes, Claude Desktop, and protocol markdown.

## License

MIT — see [LICENSE](LICENSE). Continual-learning portions derived from Cursor's plugin ([LICENSE-continual-learning](LICENSE-continual-learning)).
