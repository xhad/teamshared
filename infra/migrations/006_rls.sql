-- teamshared 006: Row-Level Security -- the hard tenant boundary.
--
-- Every org-scoped table gets ``ENABLE`` + ``FORCE ROW LEVEL SECURITY`` and a
-- policy keyed on the ``app.current_org_id`` GUC. The application sets that
-- GUC per transaction via ``teamshared.tenancy.with_org``. When it is unset,
-- ``current_setting(..., true)`` returns NULL, the comparison is NULL, and
-- *zero* rows match -- a missing tenant context fails closed, by design.
--
-- FORCE makes the policy apply even to the table owner, so isolation does not
-- depend on which role the app connects as -- with the sole exception of a
-- Postgres superuser, which always bypasses RLS. Production therefore MUST
-- connect as the non-superuser ``teamshared_app`` role (see
-- ``teamshared provision-app-role``). Migrations run as the admin role.

-- Standard per-org tables: visible only when org_id matches the GUC.
DO $$
DECLARE
    t text;
    org_tables text[] := ARRAY[
        'users', 'memberships', 'teams', 'team_members', 'projects',
        'agents', 'api_keys', 'role_bindings',
        'memory_items', 'memory_chunks', 'memory_embeddings', 'memory_versions',
        'memory_shares', 'retention_policies', 'approval_queue',
        'procedures', 'audit_events',
        'connectors', 'connector_tokens', 'connector_sync_state', 'source_documents'
    ];
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

-- organizations: a tenant may only see/modify its own row.
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_self ON organizations;
CREATE POLICY org_self ON organizations
    USING (id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (id = current_setting('app.current_org_id', true)::uuid);

-- roles: system roles (org_id NULL) are readable by everyone; org-custom roles
-- are isolated to their tenant.
ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE roles FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS role_visibility ON roles;
CREATE POLICY role_visibility ON roles
    USING (org_id IS NULL OR org_id = current_setting('app.current_org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid);

-- Best-effort: grant CRUD to the application role if it already exists. The
-- role itself is created (with LOGIN + password) out of band by
-- ``teamshared provision-app-role`` so no secret lives in a migration.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT USAGE ON SCHEMA public TO teamshared_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO teamshared_app;
        GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO teamshared_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO teamshared_app;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public
            GRANT USAGE, SELECT ON SEQUENCES TO teamshared_app;
    END IF;
END $$;
