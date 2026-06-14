-- teamshared 019: promote projects to first-class Asana-style projects.
--
-- Builds on the bare `projects` table from 002 (slug + name + team_id) by adding
-- description, lifecycle status, default view, color, and an owner, plus three
-- child tables: ordered sections (list groups / board columns), project members
-- (humans and agents), and project status updates (on-track / at-risk / off-track).

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS description_md  TEXT,
    ADD COLUMN IF NOT EXISTS project_status  TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS default_view    TEXT NOT NULL DEFAULT 'list',
    ADD COLUMN IF NOT EXISTS color           TEXT,
    ADD COLUMN IF NOT EXISTS owner_id        UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS initiative_id   UUID REFERENCES strategic_initiatives(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS created_by      TEXT,
    ADD COLUMN IF NOT EXISTS updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS archived_at     TIMESTAMPTZ;

ALTER TABLE projects
    DROP CONSTRAINT IF EXISTS projects_project_status_check;
ALTER TABLE projects
    ADD CONSTRAINT projects_project_status_check
        CHECK (project_status IN ('active', 'archived'));

ALTER TABLE projects
    DROP CONSTRAINT IF EXISTS projects_default_view_check;
ALTER TABLE projects
    ADD CONSTRAINT projects_default_view_check
        CHECK (default_view IN ('list', 'board', 'timeline', 'calendar'));

CREATE INDEX IF NOT EXISTS projects_initiative_idx
    ON projects (initiative_id) WHERE initiative_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS projects_fts_idx
    ON projects USING GIN (
        to_tsvector('english', coalesce(name, '') || ' ' || coalesce(description_md, ''))
    );

-- Ordered buckets within a project (list groups and board columns).
CREATE TABLE IF NOT EXISTS project_sections (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    sort_order  DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS project_sections_project_idx
    ON project_sections (project_id, sort_order);

-- Project membership for humans and agents.
CREATE TABLE IF NOT EXISTS project_members (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    member_type TEXT NOT NULL,
    member_id   UUID NOT NULL,
    role        TEXT NOT NULL DEFAULT 'member',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT project_members_member_type_check CHECK (member_type IN ('user', 'agent')),
    UNIQUE (org_id, project_id, member_type, member_id)
);
CREATE INDEX IF NOT EXISTS project_members_project_idx
    ON project_members (project_id);

-- Periodic project status updates (the on-track / at-risk / off-track banner).
CREATE TABLE IF NOT EXISTS project_status_updates (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    state       TEXT NOT NULL DEFAULT 'on_track',
    body_md     TEXT,
    author_type TEXT NOT NULL,
    author_id   UUID NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT project_status_updates_state_check
        CHECK (state IN ('on_track', 'at_risk', 'off_track')),
    CONSTRAINT project_status_updates_author_type_check
        CHECK (author_type IN ('user', 'agent'))
);
CREATE INDEX IF NOT EXISTS project_status_updates_project_idx
    ON project_status_updates (project_id, created_at DESC);

-- Dedicated project permissions; reuse work:* semantics but allow finer gating.
INSERT INTO permissions (code, description) VALUES
    ('project:read',  'List and view projects'),
    ('project:write', 'Create and update projects, sections, and members')
ON CONFLICT (code) DO NOTHING;

WITH role_perm(role_name, perm) AS (
    VALUES
        ('org_owner', 'project:read'), ('org_owner', 'project:write'),
        ('org_admin', 'project:read'), ('org_admin', 'project:write'),
        ('team_admin', 'project:read'), ('team_admin', 'project:write'),
        ('project_admin', 'project:read'), ('project_admin', 'project:write'),
        ('member', 'project:read'), ('member', 'project:write'),
        ('viewer', 'project:read'),
        ('agent', 'project:read'), ('agent', 'project:write'),
        ('service_account', 'project:read'), ('service_account', 'project:write')
)
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, rp.perm
FROM role_perm rp
JOIN roles r ON r.name = rp.role_name AND r.org_id IS NULL
ON CONFLICT (role_id, permission_code) DO NOTHING;

-- RLS for the new project child tables.
DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY[
        'project_sections', 'project_members', 'project_status_updates'
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
