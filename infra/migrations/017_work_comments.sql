-- teamshared 017: threaded comments on work items.

CREATE TABLE IF NOT EXISTS work_comments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    work_item_id    UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    author_type     TEXT NOT NULL,
    author_id       UUID NOT NULL,
    body_md         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT work_comments_author_type_check CHECK (author_type IN ('user', 'agent'))
);

CREATE INDEX IF NOT EXISTS work_comments_item_idx
    ON work_comments (work_item_id, created_at);

DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY['work_comments'];
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
