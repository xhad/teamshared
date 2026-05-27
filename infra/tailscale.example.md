# Exposing sptx over Tailscale

The intended production topology: one always-on host runs the compose stack;
every agent (laptop, desktop, phone) reaches it over Tailscale. No public
ports, no relay, no per-machine secret distribution beyond a single bearer
token per agent.

## On the host

1. Install Tailscale and authenticate the host:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   sudo tailscale up
   ```
2. Bring up the stack:
   ```bash
   cd sptx
   docker compose -f infra/docker-compose.yml up -d --build
   docker compose -f infra/docker-compose.yml run --rm server sptx migrate
   ```
3. Expose the MCP port over Tailscale Serve (HTTPS terminated by Tailscale):
   ```bash
   sudo tailscale serve --bg --https=443 http://127.0.0.1:8077
   ```
4. Note the URL — Tailscale prints something like
   `https://memory.tailXXXX.ts.net/`. Append `/mcp` for the MCP endpoint.

## On every agent device

```bash
sudo tailscale up
```

Mint a per-agent token on the host and paste it into the agent's MCP config.
See [`src/sptx/clients/`](../src/sptx/clients) for the exact snippets.

## Renewing tokens

Tokens are static. To rotate, run on the host:

```bash
sptx token revoke <prefix>
sptx token mint <agent>
```

…then update the new value in that agent's config.
