-- teamshared 013: global email identity (accounts) for multi-tenant console.
--
-- Until now a human was modeled per-org: the same email is a separate ``users``
-- row in every org (``UNIQUE (org_id, email)``), with no link between them. This
-- adds a global ``accounts`` table keyed by a globally-unique (lowercased) email
-- and links each per-org ``users`` row to it via ``account_id``. One account can
-- own/join many orgs; the console enumerates them at login and lets the human
-- switch between orgs.
--
-- ``accounts`` is a pre-org, cross-org auth table: it must be read/written
-- *before* an org context exists (and across orgs), which RLS forbids. So like
-- ``provision_organization`` / ``auth_lookup_api_key`` (008, 009) we keep it
-- locked (RLS + FORCE, no policy => deny all direct access for the non-superuser
-- app role) and expose only two tightly-scoped SECURITY DEFINER functions.

CREATE TABLE IF NOT EXISTS accounts (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         TEXT NOT NULL,                  -- stored lowercased
    display_name  TEXT,
    status        TEXT NOT NULL DEFAULT 'active', -- active | disabled
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS accounts_email_key ON accounts (lower(email));

-- Link every per-org user row to its global account.
ALTER TABLE users ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES accounts(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS users_account_id_idx ON users (account_id);

-- Lock the table: RLS + FORCE with no policy denies all direct access (even the
-- owner, except a superuser). Access flows only through the SECURITY DEFINER
-- functions below. Never query ``accounts`` under ``TenantDb.org(...)``.
ALTER TABLE accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE accounts FORCE ROW LEVEL SECURITY;

-- Upsert an account by (lowercased) email; returns the row. SECURITY DEFINER so
-- it works before/without an org context. Idempotent: re-activates + refreshes
-- the display name when the account already exists.
CREATE OR REPLACE FUNCTION provision_account(p_email text, p_name text DEFAULT NULL)
RETURNS accounts
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    INSERT INTO accounts (email, display_name)
    VALUES (lower(p_email), p_name)
    ON CONFLICT (lower(email)) DO UPDATE SET
        display_name = COALESCE(EXCLUDED.display_name, accounts.display_name),
        status = 'active',
        updated_at = now()
    RETURNING *
$$;

REVOKE ALL ON FUNCTION provision_account(text, text) FROM PUBLIC;

-- Enumerate every active org an email belongs to (cross-org; bypasses RLS by
-- design, same as auth_lookup_api_key). Returns the per-org user id + the
-- membership role so the console can pick/switch the active org.
CREATE OR REPLACE FUNCTION auth_account_orgs(p_email text)
RETURNS TABLE (
    org_id    UUID,
    user_id   UUID,
    org_slug  TEXT,
    org_name  TEXT,
    role      TEXT
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT u.org_id, u.id, o.slug, o.name, m.role
    FROM accounts a
    JOIN users u ON u.account_id = a.id
    JOIN organizations o ON o.id = u.org_id
    LEFT JOIN memberships m ON m.org_id = u.org_id AND m.user_id = u.id
    WHERE lower(a.email) = lower(p_email)
      AND a.status = 'active'
      AND u.status = 'active'
      AND o.status = 'active'
    ORDER BY o.created_at
$$;

REVOKE ALL ON FUNCTION auth_account_orgs(text) FROM PUBLIC;

-- Backfill: one account per distinct existing email, then link users to it.
-- Runs as the migration (admin) role, so it bypasses RLS to read every org.
INSERT INTO accounts (email)
SELECT DISTINCT lower(email) FROM users
ON CONFLICT (lower(email)) DO NOTHING;

UPDATE users u
SET account_id = a.id
FROM accounts a
WHERE a.email = lower(u.email) AND u.account_id IS NULL;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'teamshared_app') THEN
        GRANT EXECUTE ON FUNCTION provision_account(text, text) TO teamshared_app;
        GRANT EXECUTE ON FUNCTION auth_account_orgs(text) TO teamshared_app;
    END IF;
END $$;
