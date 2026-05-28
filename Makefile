

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
COMPOSE_OLLAMA_HOST := docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.ollama-host.yml

build :; $(COMPOSE) up -d --build
# Host Ollama on Linux when bridge -> host.docker.internal is blocked by firewall
build-ollama-host :; $(COMPOSE_OLLAMA_HOST) up -d --build
migrate :; $(COMPOSE) run --rm server teamshared migrate
seed :; $(COMPOSE) run --rm server teamshared seed
token-mint :; $(COMPOSE) run --rm server teamshared token mint cursor
# Paste the printed token into ~/.cursor/mcp.json using src/teamshared/clients/cursor.mcp.json as the template
health :; curl -fsS http://localhost:8077/health | jq

.PHONY: build migrate seed token-mint health

