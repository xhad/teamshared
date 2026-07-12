# Run after installing OpenClaw (requires openclaw on PATH):
openclaw config set 'mcp_servers.teamshared.url' '__MCP_URL__'
openclaw config set 'mcp_servers.teamshared.headers.Authorization' "Bearer ${TEAMSHARED_TOKEN}"
openclaw config set 'mcp_servers.teamshared.timeout' 30
openclaw daemon restart
openclaw mcp list

# Optional — memory-companion gateway (requires TEAMSHARED_GATEWAY_ENABLED=true
# on the server). Routes every model call through teamshared so each request
# gets session capture + compression + context enrichment server-side.
# Replace MODEL_ID with the upstream model the server proxies to
# (TEAMSHARED_GATEWAY_DEFAULT_MODEL or any model the upstream accepts):
openclaw config set 'models.mode' 'merge'
openclaw config set 'models.providers.teamshared.baseUrl' '__GATEWAY_URL__'
openclaw config set 'models.providers.teamshared.apiKey' "${TEAMSHARED_TOKEN}"
openclaw config set 'models.providers.teamshared.api' 'openai-completions'
openclaw config set 'models.providers.teamshared.models[0].id' 'MODEL_ID'
openclaw config set 'models.providers.teamshared.models[0].name' 'MODEL_ID via teamshared'
openclaw config set 'agents.defaults.model.primary' 'teamshared/MODEL_ID'
openclaw daemon restart
