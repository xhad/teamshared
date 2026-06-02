-- teamshared 012: curated wiki pages.
--
-- The CuratorWorker synthesizes a subject's semantic facts + recent episodes
-- into one canonical markdown article and writes it here. Each curation creates
-- a NEW version row (versioned == free page history); the latest version per
-- (org_id, slug) is the live page. ``sources`` records the contributing
-- memory_item ids for provenance and recompaction. The body is rendered through
-- the allowlist HTML sanitizer before display, so agent-authored markdown can
-- never inject executable HTML.

CREATE TABLE IF NOT EXISTS wiki_pages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    slug        TEXT NOT NULL,                       -- canonical subject slug
    version     INT  NOT NULL,                       -- monotonic per (org, slug)
    title       TEXT NOT NULL,
    body_md     TEXT NOT NULL,                       -- synthesized markdown
    sources     UUID[] NOT NULL DEFAULT '{}',        -- contributing memory_item ids
    updated_by  TEXT NOT NULL DEFAULT 'curator',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, slug, version)
);
CREATE INDEX IF NOT EXISTS wiki_pages_org_slug_idx ON wiki_pages (org_id, slug, version DESC);

-- RLS: same hard tenant boundary as every other org-scoped table (see 006).
ALTER TABLE wiki_pages ENABLE ROW LEVEL SECURITY;
ALTER TABLE wiki_pages FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation ON wiki_pages;
CREATE POLICY org_isolation ON wiki_pages
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON wiki_pages TO teamshared_app;
    END IF;
END $$;
