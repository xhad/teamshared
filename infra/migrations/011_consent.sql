-- teamshared 011: consent-first capture governance.
--
-- A ``consent_grants`` row records that a human explicitly authorized an agent
-- to share conversation data into team memory, the scope of what may be shared,
-- and the client-side sanitization profile to enforce. Capture is OFF unless an
-- active (non-revoked, non-expired, mode <> 'off') grant exists whose ``scope``
-- covers the capability being captured. Nothing is captured or pulled without an
-- active grant.

CREATE TABLE IF NOT EXISTS consent_grants (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id               UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    agent                TEXT NOT NULL,                   -- agent identity the grant covers
    mode                 TEXT NOT NULL DEFAULT 'review',  -- review|policy|off
    scope                TEXT[] NOT NULL DEFAULT '{}',    -- tool_calls|distilled_facts_only|raw_turns
    sanitization_profile JSONB NOT NULL DEFAULT '{}',     -- redaction rules enforced client-side
    granted_by           UUID,                            -- human user who approved
    granted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at           TIMESTAMPTZ,
    revoked_at           TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS consent_grants_org_idx ON consent_grants (org_id);
CREATE INDEX IF NOT EXISTS consent_grants_agent_idx ON consent_grants (org_id, agent);

-- RLS: same hard tenant boundary as every other org-scoped table (see 006).
ALTER TABLE consent_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE consent_grants FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation ON consent_grants;
CREATE POLICY org_isolation ON consent_grants
    USING (org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON consent_grants TO teamshared_app;
    END IF;
END $$;
