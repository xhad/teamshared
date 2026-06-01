-- teamshared 008: privileged auth lookup that bypasses RLS by design.
--
-- API-key authentication happens *before* an org context exists, so the
-- prefix lookup cannot satisfy the RLS policy on ``api_keys``. Rather than
-- weaken the policy, we expose one tightly-scoped SECURITY DEFINER function
-- that returns a single row by globally-unique prefix. The caller still must
-- verify the key hash; this only narrows the candidate set to one row.

CREATE OR REPLACE FUNCTION auth_lookup_api_key(p_prefix text)
RETURNS TABLE (
    id              UUID,
    org_id          UUID,
    key_hash        TEXT,
    principal_type  TEXT,
    principal_id    UUID,
    scopes          TEXT[],
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id, org_id, key_hash, principal_type, principal_id, scopes, expires_at, revoked_at
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

-- Touch last_used_at without an org context (called right after auth).
CREATE OR REPLACE FUNCTION auth_touch_api_key(p_id uuid)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    UPDATE api_keys SET last_used_at = now() WHERE id = p_id
$$;

REVOKE ALL ON FUNCTION auth_touch_api_key(uuid) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT EXECUTE ON FUNCTION auth_touch_api_key(uuid) TO teamshared_app;
    END IF;
END $$;
