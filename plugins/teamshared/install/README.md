# Install assets (curl installer source of truth)

Files here are served at ``/install/assets/{harness}/…`` by the teamshared server.
The unified ``install.sh`` / ``uninstall.sh`` scripts fetch from that URL.

**Canonical copies live in this plugin bundle only** — there is no separate
``install_assets/`` tree at the repo root.

## Layout

| Served URL | File | Notes |
|---|---|---|
| `/install/assets/cursor/teamshared.mdc` | `../rules/teamshared.mdc` | alias (memory rule) |
| `/install/assets/hermes/protocol.md` | `../clients/protocol.md` | alias (agent protocol) |
| `/install/assets/codex/mcp.toml` | `codex/mcp.toml` | Codex MCP snippet |
| `/install/assets/hermes/mcp.yaml` | `hermes/mcp.yaml` | Hermes MCP snippet |
| `/install/assets/hermes/capture.py` | `hermes/capture.py` | Hermes ``post_llm_call`` capture hook |
| `/install/assets/hermes/hooks.yaml` | `hermes/hooks.yaml` | Reference hooks block |
| `/install/assets/claude/mcp.json` | `claude/mcp.json` | Claude Desktop MCP snippet |
| `/install/assets/cursor/mcp.json` | `cursor/mcp.json` | Optional manual MCP snippet |

Placeholders ``__MCP_URL__`` and ``__TEAMSHARED_TOKEN__`` are substituted when
assets are served or after download by ``install.sh``.

## Related paths

- ``../rules/`` — ``teamshared.mdc`` / ``teamshared.md`` (Cursor rule)
- ``../clients/`` — human-readable protocol and extended examples
- ``../hooks/`` — Cursor marketplace continual-learning hook only

Resolution logic: ``teamshared.clients.install_assets``.
