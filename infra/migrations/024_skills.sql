-- teamshared 024: agent skills pillar (building blocks distinct from playbooks).
--
-- Skills are atomic, reusable instruction units (like Cursor SKILL.md files).
-- Playbooks/procedures compose skills via ``tool_recipe.skills`` and may loop
-- through them; workflows may reference a skill on a stage via ``skill``.

CREATE TABLE IF NOT EXISTS skills (
    id              BIGSERIAL PRIMARY KEY,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    scope           TEXT NOT NULL DEFAULT 'org',
    name            TEXT NOT NULL,
    version         INT  NOT NULL,
    description     TEXT,
    body_md         TEXT NOT NULL,
    tool_hints      JSONB,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'active',
    UNIQUE (org_id, name, version)
);

CREATE INDEX IF NOT EXISTS skills_org_name_idx ON skills (org_id, name);
CREATE INDEX IF NOT EXISTS skills_org_status_idx ON skills (org_id, status);
CREATE INDEX IF NOT EXISTS skills_tags_idx ON skills USING GIN (tags);
CREATE INDEX IF NOT EXISTS skills_body_fts_idx
    ON skills USING GIN (
        to_tsvector(
            'english',
            coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(body_md, '')
        )
    );

-- Approval queue: polymorphic skill target.
ALTER TABLE approval_queue
    ADD COLUMN IF NOT EXISTS skill_id BIGINT REFERENCES skills(id) ON DELETE CASCADE;

ALTER TABLE approval_queue
    DROP CONSTRAINT IF EXISTS approval_queue_target_check;

ALTER TABLE approval_queue
    ADD CONSTRAINT approval_queue_target_check CHECK (
        (memory_id IS NOT NULL AND procedure_id IS NULL AND skill_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NOT NULL AND skill_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL AND skill_id IS NOT NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL AND skill_id IS NULL
            AND strategic_entity_type IS NOT NULL AND strategic_entity_id IS NOT NULL
            AND work_item_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL AND skill_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NOT NULL)
    );

DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY['skills'];
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
