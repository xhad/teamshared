# teamshared-memory (Cursor plugin)

Connects Cursor (and documents other clients) to the [teamshared](https://github.com/sapien/teamshared)
shared-memory MCP server.

Bundled components:

| Component | Purpose |
|---|---|
| `mcp.json` | Wires `teamshared-memory` via `TEAMSHARED_URL` + `TEAMSHARED_TOKEN` |
| `rules/teamshared-memory.mdc` | Recall-first protocol (`alwaysApply`) |
| `skills/teamshared-memory/` | Tool chooser + session workflow |
| `clients/` | Copy-paste snippets for Hermes, Claude Desktop, and plain-text protocol |

## Prerequisites

1. A running teamshared server (`teamshared serve --transport http` or Docker compose).
2. A bearer token for this machine/client:

**Recommended (invite code — user never sees the admin secret)**

Admin (once per teammate):

```bash
export TEAMSHARED_PUBLIC_URL=https://mcp.example.com   # on the server
teamshared token invite-create --agent cursor-yourname
# share the printed /get-token link
```

User: open the link in a browser, or:

```bash
curl -fsS -X POST "${TEAMSHARED_URL%/mcp}/tokens/mint/INVITE_CODE/cursor-yourname"
```

**Admin / local host**

```bash
# CLI on the server
teamshared token mint cursor-yourname

# HTTP (requires TEAMSHARED_MINT_SECRET on the server)
curl -fsS -X POST "${TEAMSHARED_URL%/mcp}/tokens/mint" \
  -H 'Content-Type: application/json' \
  -H "X-Teamshared-Mint-Secret: ${TEAMSHARED_MINT_SECRET}" \
  -d '{"agent":"cursor-yourname"}'
```

3. Environment variables (add to shell profile or `.env` loaded before Cursor starts):

```bash
export TEAMSHARED_URL=http://localhost:8077/mcp
export TEAMSHARED_TOKEN=teamshared_...   # from token mint
```

For Tailscale/Railway, set `TEAMSHARED_URL` to your public `/mcp` URL instead.

## Install in Cursor

### From this repo (local dev)

```bash
ln -sf "$(pwd)/plugins/teamshared-memory" ~/.cursor/plugins/local/teamshared-memory
```

Reload Cursor (**Developer: Reload Window**). Confirm under **Settings → MCP** that
`teamshared-memory` appears and is enabled.

### Marketplace (when published)

Settings → Plugins → search **teamshared-memory**, or `/add-plugin teamshared-memory`.

## What you get in Cursor

- **MCP tools**: `memory_recall`, `memory_remember`, `memory_session_*`, etc.
- **Rule**: injects the recall-first protocol on every agent turn.
- **Skill**: `teamshared-memory` for explicit “use shared memory” workflows.

If you previously used `~/.cursor/rules/teamshared-memory.mdc` under an old name, disable or remove it to
avoid duplicate/conflicting instructions.

## Other clients

| Client | Config | Behavior protocol |
|---|---|---|
| **Hermes** | [`clients/hermes.config.yaml`](clients/hermes.config.yaml) | [`clients/protocol.md`](clients/protocol.md) |
| **Claude Desktop** | [`clients/claude-desktop.json`](clients/claude-desktop.json) | [`clients/protocol.md`](clients/protocol.md) |
| **OpenClaw** | [`../src/teamshared/clients/openclaw.md`](../src/teamshared/clients/openclaw.md) | [`clients/protocol.md`](clients/protocol.md) |
| **Cursor CLI / SDK** | `settingSources: ["plugins"]` or inline `mcpServers` | Same rule text or embed `protocol.md` in the agent prompt |

### Cursor SDK example

```typescript
const agent = Agent.create({
  apiKey: process.env.CURSOR_API_KEY!,
  model: { id: "composer-2" },
  local: { cwd: process.cwd(), settingSources: ["plugins", "user"] },
  mcpServers: {
    "teamshared-memory": {
      type: "http",
      url: process.env.TEAMSHARED_URL!,
      headers: { Authorization: `Bearer ${process.env.TEAMSHARED_TOKEN!}` },
    },
  },
});
```

Re-pass `mcpServers` on `Agent.resume()` — inline MCP config is not persisted.

## Troubleshooting

| Symptom | Fix |
|---|---|
| MCP server missing in Settings | Reload window; check symlink under `~/.cursor/plugins/local/` |
| Tools empty / 401 | Verify `TEAMSHARED_TOKEN`; mint a fresh token if revoked |
| Model never calls memory | Rule not loaded — check plugin installed; for non-Cursor hosts paste `protocol.md` |
| `${env:TEAMSHARED_URL}` not expanded | Export vars before launching Cursor from terminal, or use a login shell |

## License

MIT — same as teamshared.
