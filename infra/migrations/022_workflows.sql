-- teamshared 022: procedural-loop workflow engine.
--
-- A workflow definition is a versioned procedure whose `tool_recipe` carries a
-- validated `stages` graph (see teamshared.workflow.definition). A `workflow_run`
-- walks a set of work items through those stages: agent-owned stages auto-advance
-- by reusing the `agent_runs` executor, while human-owned stages pause as a
-- `waiting_human` step run until someone advances them. Routing can send an item
-- back to an earlier stage; the run loops over its item set until every item is
-- terminal or `max_iterations` is reached.
--
-- Both tables are org-scoped under FORCE RLS, mirroring 021_agent_runs.sql. The
-- run row is the authoritative state; `work_items.workflow_run_id` /
-- `current_stage` are denormalized pointers so the work board can show progress.

ALTER TABLE work_items
    ADD COLUMN IF NOT EXISTS workflow_run_id UUID,
    ADD COLUMN IF NOT EXISTS current_stage   TEXT;

CREATE INDEX IF NOT EXISTS work_items_workflow_run_idx
    ON work_items (workflow_run_id) WHERE workflow_run_id IS NOT NULL;

-- One execution of a workflow definition over a set of work items.
CREATE TABLE IF NOT EXISTS workflow_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    workflow_name       TEXT NOT NULL,
    workflow_version    INTEGER,

    status              TEXT NOT NULL DEFAULT 'running',
    iteration           INTEGER NOT NULL DEFAULT 0,
    max_iterations      INTEGER NOT NULL DEFAULT 10,

    selector_json       JSONB NOT NULL DEFAULT '{}',
    initiative_id       UUID REFERENCES strategic_initiatives(id) ON DELETE SET NULL,
    project_id          UUID,

    error               TEXT,

    created_by          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at        TIMESTAMPTZ,

    CONSTRAINT workflow_runs_status_check CHECK (
        status IN ('running', 'paused', 'completed', 'failed', 'cancelled')
    )
);

CREATE INDEX IF NOT EXISTS workflow_runs_org_status_idx
    ON workflow_runs (org_id, status);
CREATE INDEX IF NOT EXISTS workflow_runs_initiative_idx
    ON workflow_runs (initiative_id) WHERE initiative_id IS NOT NULL;

-- One work item's pass through one stage of a workflow run. `seq` increments
-- each time an item re-enters a stage (loop-back), so the chain is append-only
-- and the full per-item history is preserved.
CREATE TABLE IF NOT EXISTS workflow_step_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workflow_run_id     UUID NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    work_item_id        UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,

    stage_id            TEXT NOT NULL,
    owner               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    seq                 INTEGER NOT NULL DEFAULT 0,

    agent_run_id        UUID REFERENCES agent_runs(id) ON DELETE SET NULL,
    note                TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,

    CONSTRAINT workflow_step_runs_owner_check CHECK (owner IN ('agent', 'human')),
    CONSTRAINT workflow_step_runs_status_check CHECK (
        status IN ('pending', 'running', 'waiting_human', 'done', 'failed', 'skipped')
    ),
    UNIQUE (workflow_run_id, work_item_id, stage_id, seq)
);

CREATE INDEX IF NOT EXISTS workflow_step_runs_run_idx
    ON workflow_step_runs (workflow_run_id);
CREATE INDEX IF NOT EXISTS workflow_step_runs_work_idx
    ON workflow_step_runs (work_item_id);
CREATE INDEX IF NOT EXISTS workflow_step_runs_waiting_idx
    ON workflow_step_runs (org_id, status) WHERE status = 'waiting_human';

INSERT INTO permissions (code, description) VALUES
    ('workflow:read',  'List and view workflow runs and their step history'),
    ('workflow:write', 'Define workflows and start, advance, or cancel runs')
ON CONFLICT (code) DO NOTHING;

WITH role_perm(role_name, perm) AS (
    VALUES
        ('org_owner', 'workflow:read'), ('org_owner', 'workflow:write'),
        ('org_admin', 'workflow:read'), ('org_admin', 'workflow:write'),
        ('team_admin', 'workflow:read'), ('team_admin', 'workflow:write'),
        ('project_admin', 'workflow:read'), ('project_admin', 'workflow:write'),
        ('member', 'workflow:read'), ('member', 'workflow:write'),
        ('viewer', 'workflow:read'),
        ('agent', 'workflow:read'), ('agent', 'workflow:write'),
        ('service_account', 'workflow:read'), ('service_account', 'workflow:write')
)
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, rp.perm
FROM role_perm rp
JOIN roles r ON r.name = rp.role_name AND r.org_id IS NULL
ON CONFLICT (role_id, permission_code) DO NOTHING;

DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY['workflow_runs', 'workflow_step_runs'];
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
