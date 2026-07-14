-- teamshared 034: private per-person soul profiles (org + account scoped).
--
-- A soul is a tiny compressed identity document for one human in one org:
-- who they are, preferences, style, likes/dislikes, dos/don'ts. Always loaded
-- at session start for that person's agents. Never shared across accounts
-- within the org — application code filters by account_id; RLS still isolates
-- tenants by org_id.

CREATE TABLE IF NOT EXISTS soul_profiles (
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    account_id  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    body_md     TEXT NOT NULL DEFAULT '',
    version     INT  NOT NULL DEFAULT 1,
    token_est   INT  NOT NULL DEFAULT 0,
    updated_by  TEXT NOT NULL DEFAULT 'system',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, account_id)
);

CREATE INDEX IF NOT EXISTS soul_profiles_account_idx
    ON soul_profiles (account_id);

ALTER TABLE soul_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE soul_profiles FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation ON soul_profiles;
CREATE POLICY org_isolation ON soul_profiles
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON soul_profiles TO teamshared_app;
    END IF;
END $$;
