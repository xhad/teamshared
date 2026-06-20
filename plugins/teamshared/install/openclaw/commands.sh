# Run after installing OpenClaw (requires openclaw on PATH):
openclaw config set 'mcp_servers.teamshared.url' '__MCP_URL__'
openclaw config set 'mcp_servers.teamshared.headers.Authorization' "Bearer ${TEAMSHARED_TOKEN}"
openclaw config set 'mcp_servers.teamshared.timeout' 30
openclaw daemon restart
openclaw mcp list
