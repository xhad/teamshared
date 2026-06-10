

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml

build :; $(COMPOSE) up -d --build
# Optional in-compose Ollama (CPU-only on macOS); default stack uses host GPU via host.docker.internal.
build-bundled-ollama :; COMPOSE_PROFILES=bundled-ollama $(COMPOSE) up -d --build
ollama-host :; ./scripts/ollama-host.sh
down :; $(COMPOSE) down
down-all :; $(COMPOSE) down --remove-orphans
migrate :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared migrate
# Create the non-superuser app role (TEAMSHARED_PG_APP_USER) so RLS is enforced.
# Run after `migrate`, then restart the server/distiller/curator.
provision-app-role :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared provision-app-role
# Assert tenant isolation: zero rows visible with no org context set.
verify-rls :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared verify-rls
seed :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared seed
token-mint :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared token mint cursor
invite-create :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared token invite-create --agent cursor
# Paste the printed token into ~/.cursor/mcp.json using src/teamshared/clients/cursor.mcp.json as the template
health :; curl -fsS http://localhost:8077/health | jq

smoke-all :; python scripts/smoke_all_tools.py
smoke-cross-agent :; python scripts/smoke_cross_agent.py

# Quality gates (same commands CI runs). `make check` is the pre-push gate.
test :; python -m pytest
test-integration :; python -m pytest -m integration
lint :; python -m ruff check src tests scripts eval
typecheck :; python -m mypy src
check : lint typecheck test

.PHONY: build build-bundled-ollama ollama-host down down-all migrate provision-app-role verify-rls seed token-mint invite-create health smoke-all smoke-cross-agent test test-integration lint typecheck check
