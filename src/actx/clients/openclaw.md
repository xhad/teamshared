# Connecting OpenClaw to actx

OpenClaw discovers MCP servers via its plugin/config system. The exact CLI
form depends on your installed version; the canonical path is:

```bash
# Verify your build's MCP slot (output will mention `mcp_servers` or similar)
openclaw config schema | grep -i mcp

# Add actx as an MCP server (replace <agent-token>)
openclaw config set 'mcp_servers.actx-memory.url' 'https://memory.tailXXXX.ts.net/mcp'
openclaw config set 'mcp_servers.actx-memory.headers.Authorization' 'Bearer <agent-token>'
openclaw config set 'mcp_servers.actx-memory.timeout' 30

# Restart OpenClaw so it re-reads the config
openclaw daemon restart   # or: openclaw mcp reload   (depending on version)

# Confirm the tools are visible
openclaw mcp list
```

If your build instead expects MCP servers declared in `~/.openclaw/config.yaml`
directly, paste this block:

```yaml
mcp_servers:
  actx-memory:
    url: https://memory.tailXXXX.ts.net/mcp
    headers:
      Authorization: "Bearer <agent-token>"
    timeout: 30
```

Mint OpenClaw's token on the actx host with:

```bash
actx token mint openclaw
```
