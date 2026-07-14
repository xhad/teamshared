

COMPOSE := docker compose --env-file .env -f infra/docker-compose.yml
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

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
# Re-embed all memory chunks with the active embedder (run once after switching
# TEAMSHARED_EMBED_PROVIDER/model; search only ranks vectors from the active model).
reembed :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared reembed
token-mint :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared token mint cursor
invite-create :; $(COMPOSE) up -d postgres redis && $(COMPOSE) run --no-deps --rm server teamshared token invite-create --agent cursor
# Paste the printed token into ~/.cursor/mcp.json (see plugins/teamshared/install/cursor/mcp.json)
health :; curl -fsS http://localhost:8077/health | jq

smoke-all :; $(PYTHON) scripts/smoke_all_tools.py
# A/B eval: same agent with vs without teamshared memory (see eval/agentic/README.md).
eval-agentic :; $(PYTHON) eval/agentic/runner.py --trials 3
# Conversation replay: token cost baseline vs teamshared per turn (see eval/conversation_replay.example.yaml).
eval-conversation :; $(PYTHON) eval/conversation_replay.py eval/conversation_replay.example.yaml
# Run bundled fixtures and open comparison dashboard (eval/conversation_replay/results/dashboard.html).
eval-conversation-report :; $(PYTHON) eval/conversation_replay_report.py
eval-conversation-report-http :; $(PYTHON) eval/conversation_replay_report.py --mode http
# Session cumulative token cost: baseline vs teamshared (see eval/conversation_replay/README.md).
eval-conversation-cost :; $(PYTHON) eval/conversation_replay/compare_cost.py eval/conversation_replay.example.yaml; $(PYTHON) eval/conversation_replay/compare_cost.py eval/conversation_replay.teamshared.yaml
open-conversation-dashboard : eval-conversation-report
	@open eval/conversation_replay/results/dashboard.html
smoke-cross-agent :; $(PYTHON) scripts/smoke_cross_agent.py

# Quality gates (same commands CI runs). `make check` is the pre-push gate.
test :; $(PYTHON) -m pytest
test-integration :; $(PYTHON) -m pytest -m integration
lint :; $(PYTHON) -m ruff check src tests scripts eval
typecheck :; $(PYTHON) -m mypy src
check : lint typecheck test

.PHONY: build build-bundled-ollama ollama-host down down-all migrate provision-app-role verify-rls seed reembed token-mint invite-create health eval-agentic eval-conversation eval-conversation-report eval-conversation-report-http eval-conversation-cost open-conversation-dashboard smoke-all smoke-cross-agent test test-integration lint typecheck check
