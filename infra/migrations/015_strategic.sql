-- teamshared 015: Strategic memory pillar — vision/mission/purpose + OKR cycles.

CREATE TABLE IF NOT EXISTS strategic_statements (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,  -- vision | mission | purpose
    content_md      TEXT NOT NULL,
    version         INT NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'pending_approval',
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, kind, version)
);
CREATE INDEX IF NOT EXISTS strategic_statements_org_kind_idx
    ON strategic_statements (org_id, kind, status);
CREATE INDEX IF NOT EXISTS strategic_statements_fts_idx
    ON strategic_statements USING GIN (
        to_tsvector('english', coalesce(kind, '') || ' ' || coalesce(content_md, ''))
    );

CREATE TABLE IF NOT EXISTS strategic_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending_approval',
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS strategic_plans_org_status_idx
    ON strategic_plans (org_id, status);
CREATE INDEX IF NOT EXISTS strategic_plans_fts_idx
    ON strategic_plans USING GIN (
        to_tsvector('english', coalesce(name, ''))
    );

CREATE TABLE IF NOT EXISTS strategic_objectives (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    plan_id         UUID NOT NULL REFERENCES strategic_plans(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description_md  TEXT,
    owner_type      TEXT,
    owner_id        UUID,
    sort_order      INT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending_approval',
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS strategic_objectives_plan_idx
    ON strategic_objectives (plan_id, status);
CREATE INDEX IF NOT EXISTS strategic_objectives_fts_idx
    ON strategic_objectives USING GIN (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description_md, ''))
    );

CREATE TABLE IF NOT EXISTS strategic_key_results (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    objective_id    UUID NOT NULL REFERENCES strategic_objectives(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    description_md  TEXT,
    metric_target   REAL,
    metric_current  REAL,
    metric_unit     TEXT,
    track_status    TEXT NOT NULL DEFAULT 'on_track',
    status          TEXT NOT NULL DEFAULT 'pending_approval',
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS strategic_key_results_objective_idx
    ON strategic_key_results (objective_id, status);
CREATE INDEX IF NOT EXISTS strategic_key_results_fts_idx
    ON strategic_key_results USING GIN (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description_md, ''))
    );

CREATE TABLE IF NOT EXISTS strategic_initiatives (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    plan_id         UUID NOT NULL REFERENCES strategic_plans(id) ON DELETE CASCADE,
    objective_id    UUID REFERENCES strategic_objectives(id) ON DELETE SET NULL,
    key_result_id   UUID REFERENCES strategic_key_results(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    description_md  TEXT,
    status          TEXT NOT NULL DEFAULT 'pending_approval',
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS strategic_initiatives_plan_idx
    ON strategic_initiatives (plan_id, status);
CREATE INDEX IF NOT EXISTS strategic_initiatives_fts_idx
    ON strategic_initiatives USING GIN (
        to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description_md, ''))
    );

-- Approval queue: polymorphic strategic target.
ALTER TABLE approval_queue
    ADD COLUMN IF NOT EXISTS strategic_entity_type TEXT,
    ADD COLUMN IF NOT EXISTS strategic_entity_id UUID;

ALTER TABLE approval_queue
    DROP CONSTRAINT IF EXISTS approval_queue_target_check;

ALTER TABLE approval_queue
    ADD CONSTRAINT approval_queue_target_check CHECK (
        (memory_id IS NOT NULL AND procedure_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NOT NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL
            AND strategic_entity_type IS NOT NULL AND strategic_entity_id IS NOT NULL)
    );

-- RLS for new tables.
DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY[
        'strategic_statements', 'strategic_plans', 'strategic_objectives',
        'strategic_key_results', 'strategic_initiatives'
    ];
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
    END LOOP;
END $$;
