

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
COMPOSE_OLLAMA_HOST := docker compose --env-file .env -f infra/docker-compose.yml -f infra/docker-compose.ollama-host.yml

build :; $(COMPOSE) up -d --build
# Host Ollama on Linux when bridge -> host.docker.internal is blocked by firewall
build-ollama-host :; $(COMPOSE_OLLAMA_HOST) up -d --build
down :; $(COMPOSE_OLLAMA_HOST) down
down-all :; $(COMPOSE_OLLAMA_HOST) down --remove-orphans
migrate :; $(COMPOSE) run --no-deps --rm server teamshared migrate
seed :; $(COMPOSE) run --no-deps --rm server teamshared seed
token-mint :; $(COMPOSE) run --no-deps --rm server teamshared token mint cursor
invite-create :; $(COMPOSE) run --no-deps --rm server teamshared token invite-create --agent cursor-chad
invite-create-host :; $(COMPOSE_OLLAMA_HOST) run --no-deps --rm server teamshared token invite-create --agent cursor-chad
# Paste the printed token into ~/.cursor/mcp.json using src/teamshared/clients/cursor.mcp.json as the template
health :; curl -fsS http://localhost:8077/health | jq

.PHONY: build build-ollama-host down down-all migrate seed token-mint invite-create invite-create-host health

