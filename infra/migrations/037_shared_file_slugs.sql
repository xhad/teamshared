-- teamshared 037: human-readable slugs for shared files.
--
-- Adds a unique `slug` to shared_files, generated from the title on publish, so
-- public URLs are memorable (/s/sapien-yield-vault-modeller) instead of UUIDs.
-- The UUID share_token is retained as the bucket-mirror key and as a fallback
-- URL. The public route detects UUID vs slug and dispatches accordingly.
--
-- Backfills a slug for every already-published file (collision-safe).

ALTER TABLE shared_files ADD COLUMN IF NOT EXISTS slug TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS shared_files_slug_idx
  ON shared_files (slug) WHERE slug IS NOT NULL;

-- SQL slugify: lowercase, non-alnum -> '-', trim leading/trailing '-'.
CREATE OR REPLACE FUNCTION shared_file_slugify(p_title TEXT)
RETURNS TEXT LANGUAGE sql IMMUTABLE AS $$
  SELECT btrim(
    regexp_replace(lower(coalesce(p_title, '')), '[^a-z0-9]+', '-', 'g'),
    '-'
  );
$$;

-- Backfill published files lacking a slug (collision-safe, global namespace).
DO $$
DECLARE
  r RECORD;
  base TEXT;
  cand TEXT;
  n INT;
BEGIN
  FOR r IN SELECT id, title FROM shared_files
           WHERE slug IS NULL AND visibility = 'published' LOOP
    base := coalesce(shared_file_slugify(r.title), 'file');
    IF base = '' THEN base := 'file'; END IF;
    cand := base;
    n := 1;
    WHILE EXISTS (SELECT 1 FROM shared_files WHERE slug = cand AND id <> r.id) LOOP
      n := n + 1;
      cand := base || '-' || n::text;
    END LOOP;
    UPDATE shared_files SET slug = cand, updated_at = now() WHERE id = r.id;
  END LOOP;
END $$;

-- Public lookups by slug (SECURITY DEFINER, fail closed: published AND active).
-- Returns the same columns as the by_token functions plus share_token (needed
-- for the bucket direct_url, since the slug path doesn't carry the token).

CREATE OR REPLACE FUNCTION public_shared_file_by_slug(p_slug TEXT)
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
    file_updated     TIMESTAMPTZ,
    share_token      UUID
)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT p.id, p.org_id, p.title, p.content_format, p.current_version,
           pv.version, pv.content, pv.content_format, pv.author_label,
           pv.created_at, p.created_at, p.updated_at, p.share_token
    FROM shared_files p
    JOIN shared_file_versions pv ON pv.file_id = p.id AND pv.version = p.current_version
    WHERE p.slug = p_slug
      AND p.visibility = 'published'
      AND p.status = 'active'
$$;
REVOKE ALL ON FUNCTION public_shared_file_by_slug(TEXT) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public_shared_file_version_by_slug(p_slug TEXT, p_version INT)
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
    file_updated     TIMESTAMPTZ,
    share_token      UUID
)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT p.id, p.org_id, p.title, p.content_format, p.current_version,
           pv.version, pv.content, pv.content_format, pv.author_label,
           pv.created_at, p.created_at, p.updated_at, p.share_token
    FROM shared_files p
    JOIN shared_file_versions pv ON pv.file_id = p.id AND pv.version = p_version
    WHERE p.slug = p_slug
      AND p.visibility = 'published'
      AND p.status = 'active'
$$;
REVOKE ALL ON FUNCTION public_shared_file_version_by_slug(TEXT, INT) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public_shared_file_versions_list_by_slug(p_slug TEXT)
RETURNS TABLE (
    version      INT,
    author_label TEXT,
    created_at   TIMESTAMPTZ
)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
    SELECT pv.version, pv.author_label, pv.created_at
    FROM shared_files p
    JOIN shared_file_versions pv ON pv.file_id = p.id
    WHERE p.slug = p_slug
      AND p.visibility = 'published'
      AND p.status = 'active'
    ORDER BY pv.version DESC
$$;
REVOKE ALL ON FUNCTION public_shared_file_versions_list_by_slug(TEXT) FROM PUBLIC;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
    GRANT EXECUTE ON FUNCTION public_shared_file_by_slug(TEXT) TO teamshared_app;
    GRANT EXECUTE ON FUNCTION public_shared_file_version_by_slug(TEXT, INT) TO teamshared_app;
    GRANT EXECUTE ON FUNCTION public_shared_file_versions_list_by_slug(TEXT) TO teamshared_app;
  END IF;
END $$;
