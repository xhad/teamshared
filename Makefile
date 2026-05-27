

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml

build :; $(COMPOSE) up -d --build
migrate :; $(COMPOSE) run --rm server sptx migrate
seed :; $(COMPOSE) run --rm server sptx seed
token-mint :; $(COMPOSE) run --rm server sptx token mint cursor
# Paste the printed token into ~/.cursor/mcp.json using src/sptx/clients/cursor.mcp.json as the template
health :; curl -fsS http://localhost:8077/health | jq

.PHONY: build migrate seed token-mint health

