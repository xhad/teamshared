-- teamshared 016: Work pillar — org-scoped tasks for humans and agents.

CREATE TABLE IF NOT EXISTS work_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    initiative_id       UUID REFERENCES strategic_initiatives(id) ON DELETE SET NULL,

    title               TEXT NOT NULL,
    description_md      TEXT,
    tags                TEXT[] NOT NULL DEFAULT '{}',

    work_status         TEXT NOT NULL DEFAULT 'backlog',
    priority            TEXT NOT NULL DEFAULT 'normal',
    blocked_reason      TEXT,

    requester_type      TEXT,
    requester_id        UUID,
    assignee_type       TEXT,
    assignee_id         UUID,

    due_at              TIMESTAMPTZ,
    repo                TEXT,
    github              TEXT,

    source              TEXT NOT NULL DEFAULT 'human',

    status              TEXT NOT NULL DEFAULT 'active',
    created_by          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at           TIMESTAMPTZ,

    CONSTRAINT work_items_work_status_check CHECK (
        work_status IN ('backlog', 'todo', 'in_progress', 'blocked', 'done', 'cancelled')
    ),
    CONSTRAINT work_items_priority_check CHECK (
        priority IN ('urgent', 'high', 'normal', 'low')
    ),
    CONSTRAINT work_items_approval_status_check CHECK (
        status IN ('active', 'pending_approval', 'rejected', 'closed')
    ),
    CONSTRAINT work_items_party_type_check CHECK (
        (requester_type IS NULL AND requester_id IS NULL)
        OR requester_type IN ('user', 'agent')
    ),
    CONSTRAINT work_items_assignee_type_check CHECK (
        (assignee_type IS NULL AND assignee_id IS NULL)
        OR assignee_type IN ('user', 'agent')
    )
);

CREATE INDEX IF NOT EXISTS work_items_org_status_idx
    ON work_items (org_id, status, work_status);
CREATE INDEX IF NOT EXISTS work_items_assignee_idx
    ON work_items (org_id, assignee_type, assignee_id)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS work_items_initiative_idx
    ON work_items (initiative_id)
    WHERE initiative_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS work_items_fts_idx
    ON work_items USING GIN (
        to_tsvector(
            'english',
            coalesce(title, '') || ' ' || coalesce(description_md, '')
            || ' ' || coalesce(blocked_reason, '')
        )
    );

-- Approval queue: polymorphic work target.
ALTER TABLE approval_queue
    ADD COLUMN IF NOT EXISTS work_item_id UUID REFERENCES work_items(id) ON DELETE CASCADE;

ALTER TABLE approval_queue
    DROP CONSTRAINT IF EXISTS approval_queue_target_check;

ALTER TABLE approval_queue
    ADD CONSTRAINT approval_queue_target_check CHECK (
        (memory_id IS NOT NULL AND procedure_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NOT NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL
            AND strategic_entity_type IS NOT NULL AND strategic_entity_id IS NOT NULL
            AND work_item_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NOT NULL)
    );

INSERT INTO permissions (code, description) VALUES
    ('work:read',  'List and view work items'),
    ('work:write', 'Create and update work items')
ON CONFLICT (code) DO NOTHING;

WITH role_perm(role_name, perm) AS (
    VALUES
        ('org_owner', 'work:read'), ('org_owner', 'work:write'),
        ('org_admin', 'work:read'), ('org_admin', 'work:write'),
        ('team_admin', 'work:read'), ('team_admin', 'work:write'),
        ('project_admin', 'work:read'), ('project_admin', 'work:write'),
        ('member', 'work:read'), ('member', 'work:write'),
        ('viewer', 'work:read'),
        ('agent', 'work:read'), ('agent', 'work:write'),
        ('service_account', 'work:read'), ('service_account', 'work:write')
)
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, rp.perm
FROM role_perm rp
JOIN roles r ON r.name = rp.role_name AND r.org_id IS NULL
ON CONFLICT (role_id, permission_code) DO NOTHING;

DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY['work_items'];
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
