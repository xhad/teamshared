-- teamshared 032: remove the agent/workflow execution stack and decouple
-- memory attribution from the agents registry.
--
-- Agent *identity* is no longer a first-class registry row. Bearer (``tsk_``)
-- API keys are now org-bound principals that carry a free-text ``label`` used
-- for memory authorship/audit. Memory rows record that label directly in
-- ``author_label`` instead of joining the ``agents`` table on
-- ``owner_type = 'agent'``. The cloud-agent runner and workflow orchestrator
-- (migrations 021/022/023) are gone, so their tables are dropped.

-- 1. Free-text attribution label on keys (drives Principal.display).
ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS label TEXT;

-- 2. Free-text author label on memory rows (replaces the agents join).
ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS author_label TEXT;

-- 3. Backfill labels from the agents registry before it disappears.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'agents'
    ) THEN
        UPDATE memory_items mi
           SET author_label = a.name
          FROM agents a
         WHERE mi.owner_type = 'agent'
           AND mi.owner_id = a.id
           AND mi.author_label IS NULL;

        UPDATE api_keys k
           SET label = a.name
          FROM agents a
         WHERE k.principal_type = 'agent'
           AND k.principal_id = a.id
           AND k.label IS NULL;
    END IF;
END $$;

-- Fall back to the key name where no agent label was found.
UPDATE api_keys SET label = name WHERE label IS NULL;

-- 4. Drop the cloud-agent run + workflow execution tables.
DROP TABLE IF EXISTS workflow_step_runs CASCADE;
DROP TABLE IF EXISTS workflow_runs CASCADE;
DROP TABLE IF EXISTS agent_model_calls CASCADE;
DROP TABLE IF EXISTS agent_trace_events CASCADE;
DROP TABLE IF EXISTS agent_runs CASCADE;

-- 5. Drop the agents registry. API-key auth no longer joins it; RBAC binds the
--    org's agent principal (principal_id = org_id) to the ``agent`` role.
DROP TABLE IF EXISTS agents CASCADE;

-- 6. Authentication lookup must surface ``label`` so the resolved Principal can
--    carry it as ``display`` for attribution.
DROP FUNCTION IF EXISTS auth_lookup_api_key(text);
CREATE OR REPLACE FUNCTION auth_lookup_api_key(p_prefix text)
RETURNS TABLE (
    id              UUID,
    org_id          UUID,
    key_hash        TEXT,
    principal_type  TEXT,
    principal_id    UUID,
    scopes          TEXT[],
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    label           TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id, org_id, key_hash, principal_type, principal_id, scopes,
           expires_at, revoked_at, label
    FROM api_keys
    WHERE prefix = p_prefix
$$;

REVOKE ALL ON FUNCTION auth_lookup_api_key(text) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT EXECUTE ON FUNCTION auth_lookup_api_key(text) TO teamshared_app;
    END IF;
END $$;

-- 7. Helpful index for author-scoped recall filters.
CREATE INDEX IF NOT EXISTS memory_items_author_label_idx
    ON memory_items (org_id, author_label);
