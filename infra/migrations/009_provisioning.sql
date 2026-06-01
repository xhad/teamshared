-- teamshared 009: org provisioning that bypasses RLS by design.
--
-- Creating an organization is the one write that cannot satisfy the org RLS
-- policy (the new id is not yet the current tenant). A single SECURITY
-- DEFINER function performs it; everything else (users, teams, api keys) is
-- created afterwards inside the new org's context and passes WITH CHECK.

CREATE OR REPLACE FUNCTION provision_organization(p_slug text, p_name text)
RETURNS organizations
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO organizations (slug, name)
    VALUES (p_slug, p_name)
    RETURNING *
$$;

REVOKE ALL ON FUNCTION provision_organization(text, text) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT EXECUTE ON FUNCTION provision_organization(text, text) TO teamshared_app;
    END IF;
END $$;
