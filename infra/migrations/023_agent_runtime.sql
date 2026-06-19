-- teamshared 023: distinguish user agents from cloud agents.
--
-- A `user` agent runs on a teammate's own machine (their local Cursor/Codex/
-- etc.) and connects over MCP with a bearer token; the server never executes a
-- model for it -- it pulls work assigned to it. A `cloud` agent is one the
-- server can execute autonomously via the background worker (AgentRunner), so
-- assigning a task to a cloud agent can trigger a run automatically.
--
-- Existing agents default to `user`: the agents in the system today are local
-- MCP clients, not server-executed runners. Mark an agent `cloud` explicitly to
-- make it server-runnable.

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS runtime TEXT NOT NULL DEFAULT 'user';

ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_runtime_check;
ALTER TABLE agents
    ADD CONSTRAINT agents_runtime_check CHECK (runtime IN ('user', 'cloud'));
