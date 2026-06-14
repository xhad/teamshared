-- teamshared 020: task hierarchy + multi-project membership (Asana parity).
--
-- A task can live in many projects (Asana behaviour); its section and ordering
-- are properties of each membership, not of the task, so they live in the
-- `work_item_projects` join table. Adds subtasks (`parent_id`), task
-- dependencies, and followers/collaborators.

ALTER TABLE work_items
    ADD COLUMN IF NOT EXISTS parent_id  UUID REFERENCES work_items(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS start_at   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS item_type  TEXT NOT NULL DEFAULT 'task';

ALTER TABLE work_items
    DROP CONSTRAINT IF EXISTS work_items_item_type_check;
ALTER TABLE work_items
    ADD CONSTRAINT work_items_item_type_check
        CHECK (item_type IN ('task', 'milestone', 'approval'));

CREATE INDEX IF NOT EXISTS work_items_parent_idx
    ON work_items (parent_id) WHERE parent_id IS NOT NULL;

-- Task <-> project membership. Section and ordering are per-membership.
CREATE TABLE IF NOT EXISTS work_item_projects (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    work_item_id  UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    project_id    UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    section_id    UUID REFERENCES project_sections(id) ON DELETE SET NULL,
    sort_order    DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, work_item_id, project_id)
);
CREATE INDEX IF NOT EXISTS work_item_projects_project_idx
    ON work_item_projects (project_id, section_id, sort_order);
CREATE INDEX IF NOT EXISTS work_item_projects_item_idx
    ON work_item_projects (work_item_id);

-- Directed dependencies: `blocker` must finish before `blocked` can proceed.
CREATE TABLE IF NOT EXISTS work_dependencies (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    blocker_id  UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    blocked_id  UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT work_dependencies_no_self CHECK (blocker_id <> blocked_id),
    UNIQUE (org_id, blocker_id, blocked_id)
);
CREATE INDEX IF NOT EXISTS work_dependencies_blocked_idx
    ON work_dependencies (blocked_id);
CREATE INDEX IF NOT EXISTS work_dependencies_blocker_idx
    ON work_dependencies (blocker_id);

-- Followers / collaborators (humans and agents) watching a task.
CREATE TABLE IF NOT EXISTS work_followers (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    work_item_id  UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    follower_type TEXT NOT NULL,
    follower_id   UUID NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT work_followers_type_check CHECK (follower_type IN ('user', 'agent')),
    UNIQUE (org_id, work_item_id, follower_type, follower_id)
);
CREATE INDEX IF NOT EXISTS work_followers_item_idx
    ON work_followers (work_item_id);

DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY[
        'work_item_projects', 'work_dependencies', 'work_followers'
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
