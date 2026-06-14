-- teamshared 021: background worker agent runs + execution traces.
--
-- An agent run is one asynchronous, single-shot execution of a Work Board task
-- by a worker agent. The run row is the authoritative state machine (the Redis
-- stream is only a delivery hint); a DB-guarded lease (status + lease_expires_at)
-- makes execution idempotent so a duplicate stream delivery can never double-run.
-- Trace events and model-call metadata give a human-readable, redacted timeline
-- without reading process logs. All three tables are org-scoped under FORCE RLS.

CREATE TABLE IF NOT EXISTS agent_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    work_item_id        UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    agent_id            UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

    playbook_name       TEXT,
    playbook_version    INTEGER,

    status              TEXT NOT NULL DEFAULT 'queued',
    cancel_requested    BOOLEAN NOT NULL DEFAULT FALSE,

    model               TEXT,
    provider            TEXT,
    request_id          TEXT,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    latency_ms          INTEGER,
    error               TEXT,

    -- Lease for crash-safe, single-owner execution.
    attempt             INTEGER NOT NULL DEFAULT 0,
    lease_owner         TEXT,
    lease_expires_at    TIMESTAMPTZ,

    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    created_by          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT agent_runs_status_check CHECK (
        status IN ('queued', 'running', 'completed', 'failed', 'paused', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS agent_runs_org_status_idx
    ON agent_runs (org_id, status);
CREATE INDEX IF NOT EXISTS agent_runs_work_idx
    ON agent_runs (work_item_id);
CREATE INDEX IF NOT EXISTS agent_runs_agent_idx
    ON agent_runs (org_id, agent_id);

-- Ordered, append-only execution timeline for a run.
CREATE TABLE IF NOT EXISTS agent_trace_events (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    run_id       UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    event_type   TEXT NOT NULL,
    sequence     INTEGER NOT NULL,
    summary      TEXT,
    payload_json JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, sequence)
);
CREATE INDEX IF NOT EXISTS agent_trace_events_run_idx
    ON agent_trace_events (run_id, sequence);

-- Redacted per-call model metadata (no raw prompt/response bodies).
CREATE TABLE IF NOT EXISTS agent_model_calls (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    run_id             UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    model              TEXT,
    provider           TEXT,
    request_id         TEXT,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    latency_ms         INTEGER,
    error              TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_model_calls_run_idx
    ON agent_model_calls (run_id, created_at);

INSERT INTO permissions (code, description) VALUES
    ('agentrun:read',  'List and view agent runs and traces'),
    ('agentrun:write', 'Assign agents to work and control agent runs')
ON CONFLICT (code) DO NOTHING;

WITH role_perm(role_name, perm) AS (
    VALUES
        ('org_owner', 'agentrun:read'), ('org_owner', 'agentrun:write'),
        ('org_admin', 'agentrun:read'), ('org_admin', 'agentrun:write'),
        ('team_admin', 'agentrun:read'), ('team_admin', 'agentrun:write'),
        ('project_admin', 'agentrun:read'), ('project_admin', 'agentrun:write'),
        ('member', 'agentrun:read'), ('member', 'agentrun:write'),
        ('viewer', 'agentrun:read'),
        ('agent', 'agentrun:read'), ('agent', 'agentrun:write'),
        ('service_account', 'agentrun:read'), ('service_account', 'agentrun:write')
)
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, rp.perm
FROM role_perm rp
JOIN roles r ON r.name = rp.role_name AND r.org_id IS NULL
ON CONFLICT (role_id, permission_code) DO NOTHING;

DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY['agent_runs', 'agent_trace_events', 'agent_model_calls'];
BEGIN
    FOREACH t IN ARRAY org_tables LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS org_isolation ON %I', t);
        EXECUTE format(
            'CREATE POLICY org_isolation ON %I '
            'USING (org_id = current_setting(''app.current_org_id'', true)::uuid) '
            'WITH CHECK (org_id = current_setting(''app.current_org_id'', true)::uuid)',
            t
        );
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
            EXECUTE format(
                'GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO teamshared_app', t
            );
        END IF;
    END LOOP;
END $$;
