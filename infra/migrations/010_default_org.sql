-- teamshared 010: bootstrap a single default org for legacy-token convergence.
--
-- G2 maps every legacy ``teamshared_`` bearer token into one shared "default"
-- org (auto-provisioned agents resolve inside it). Creating the org is the one
-- write that cannot satisfy the org RLS policy by itself, so we set the
-- ``app.current_org_id`` GUC to the fixed id first; the INSERT then passes the
-- ``org_self`` WITH CHECK from migration 006. The id is fixed so application
-- config (``TEAMSHARED_DEFAULT_ORG_ID``) can reference it without a lookup.

DO $$
DECLARE
    default_id uuid := '00000000-0000-0000-0000-000000000001';
BEGIN
    PERFORM set_config('app.current_org_id', default_id::text, true);
    INSERT INTO organizations (id, slug, name)
    VALUES (default_id, 'default', 'Default Org')
    ON CONFLICT (slug) DO NOTHING;
END $$;
