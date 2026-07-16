-- teamshared 036: public versioned shared files.
--
-- Shared files are HTML or Markdown documents authored by agents (via MCP
-- tools) or humans (via the console), stored canonically in Postgres and
-- mirrored to a Railway S3-compatible bucket for public CDN serving. Each
-- update creates a new immutable version row (append-only history, same model
-- as wiki_pages / skills); the latest version per file is the live content.
--
-- Shared files default to ``visibility='private'``. An explicit publish action
-- sets ``visibility='published'`` and stamps a ``share_token`` UUID; the public
-- URL is ``/s/{share_token}``. Unpublishing flips visibility back to private
-- (the token is retained for audit) -- the public route then 404s.

CREATE TABLE IF NOT EXISTS shared_files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    content_format  TEXT NOT NULL DEFAULT 'markdown',   -- 'markdown' | 'html'
    visibility      TEXT NOT NULL DEFAULT 'private',    -- 'private' | 'published'
    share_token     UUID,                                -- set on first publish
    current_version INT  NOT NULL DEFAULT 1,
    status          TEXT NOT NULL DEFAULT 'active',      -- 'active' | 'archived'
    created_by      TEXT NOT NULL DEFAULT 'agent',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS shared_files_org_status_idx ON shared_files (org_id, status);
CREATE INDEX IF NOT EXISTS shared_files_org_visibility_idx ON shared_files (org_id, visibility);
CREATE UNIQUE INDEX IF NOT EXISTS shared_files_share_token_idx ON shared_files (share_token) WHERE share_token IS NOT NULL;

-- Append-only version history. Each update inserts a new row; old rows are
-- never mutated. ``UNIQUE (file_id, version)`` makes ``MAX(version)+1`` safe.
CREATE TABLE IF NOT EXISTS shared_file_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id         UUID NOT NULL REFERENCES shared_files(id) ON DELETE CASCADE,
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    version         INT  NOT NULL,
    content         TEXT NOT NULL,
    content_format  TEXT NOT NULL DEFAULT 'markdown',   -- 'markdown' | 'html'
    author_label    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (file_id, version)
);

CREATE INDEX IF NOT EXISTS shared_file_versions_file_idx ON shared_file_versions (file_id, version DESC);
CREATE INDEX IF NOT EXISTS shared_file_versions_org_idx ON shared_file_versions (org_id);

-- RLS: same hard tenant boundary as every other org-scoped table (see 006).
DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY['shared_files', 'shared_file_versions'];
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

-- Public read path: the /s/{share_token} route has no authenticated
-- principal and therefore no org GUC, so RLS would deny everything. This
-- SECURITY DEFINER function bypasses RLS by design (same pattern as
-- auth_account_orgs in 013) but fails closed: it returns a row only when the
-- file is published AND active. Never returns private/unpublished files.
CREATE OR REPLACE FUNCTION public_shared_file_by_token(p_token UUID)
RETURNS TABLE (
    file_id          UUID,
    org_id           UUID,
    title            TEXT,
    content_format   TEXT,
    current_version  INT,
    version          INT,
    content          TEXT,
    version_format   TEXT,
    author_label     TEXT,
    version_created  TIMESTAMPTZ,
    file_created     TIMESTAMPTZ,
    file_updated     TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT p.id, p.org_id, p.title, p.content_format, p.current_version,
           pv.version, pv.content, pv.content_format, pv.author_label,
           pv.created_at, p.created_at, p.updated_at
    FROM shared_files p
    JOIN shared_file_versions pv ON pv.file_id = p.id AND pv.version = p.current_version
    WHERE p.share_token = p_token
      AND p.visibility = 'published'
      AND p.status = 'active'
$$;

REVOKE ALL ON FUNCTION public_shared_file_by_token(UUID) FROM PUBLIC;

-- Fetch a specific published version by token + version number (public).
CREATE OR REPLACE FUNCTION public_shared_file_version_by_token(p_token UUID, p_version INT)
RETURNS TABLE (
    file_id          UUID,
    org_id           UUID,
    title            TEXT,
    content_format   TEXT,
    current_version  INT,
    version          INT,
    content          TEXT,
    version_format   TEXT,
    author_label     TEXT,
    version_created  TIMESTAMPTZ,
    file_created     TIMESTAMPTZ,
    file_updated     TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT p.id, p.org_id, p.title, p.content_format, p.current_version,
           pv.version, pv.content, pv.content_format, pv.author_label,
           pv.created_at, p.created_at, p.updated_at
    FROM shared_files p
    JOIN shared_file_versions pv ON pv.file_id = p.id AND pv.version = p_version
    WHERE p.share_token = p_token
      AND p.visibility = 'published'
      AND p.status = 'active'
$$;

REVOKE ALL ON FUNCTION public_shared_file_version_by_token(UUID, INT) FROM PUBLIC;

-- List a published file's version numbers (for the public version sidebar).
CREATE OR REPLACE FUNCTION public_shared_file_versions_list(p_token UUID)
RETURNS TABLE (
    version      INT,
    author_label TEXT,
    created_at   TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT pv.version, pv.author_label, pv.created_at
    FROM shared_files p
    JOIN shared_file_versions pv ON pv.file_id = p.id
    WHERE p.share_token = p_token
      AND p.visibility = 'published'
      AND p.status = 'active'
    ORDER BY pv.version DESC
$$;

REVOKE ALL ON FUNCTION public_shared_file_versions_list(UUID) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT EXECUTE ON FUNCTION public_shared_file_by_token(UUID) TO teamshared_app;
        GRANT EXECUTE ON FUNCTION public_shared_file_version_by_token(UUID, INT) TO teamshared_app;
        GRANT EXECUTE ON FUNCTION public_shared_file_versions_list(UUID) TO teamshared_app;
    END IF;
END $$;
