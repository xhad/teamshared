-- teamshared 003: first-class identities, API keys, and RBAC.
--
-- Agents and API keys are first-class principals with scoped permissions,
-- not just an attribution string. ``api_keys`` stores only a hash + prefix;
-- the raw secret is shown once at mint time and never persisted.

CREATE TABLE IF NOT EXISTS agents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'agent',   -- agent | service_account
    status      TEXT NOT NULL DEFAULT 'active',  -- active | disabled
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);
CREATE INDEX IF NOT EXISTS agents_org_idx ON agents (org_id);

CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    prefix          TEXT NOT NULL,              -- public lookup prefix (e.g. tsk_ab12cd34)
    key_hash        TEXT NOT NULL,              -- argon2/bcrypt hash of the full secret
    principal_type  TEXT NOT NULL,              -- user | agent
    principal_id    UUID NOT NULL,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    revoked_at      TIMESTAMPTZ,
    UNIQUE (prefix)
);
CREATE INDEX IF NOT EXISTS api_keys_org_idx ON api_keys (org_id);
CREATE INDEX IF NOT EXISTS api_keys_principal_idx ON api_keys (org_id, principal_type, principal_id);

-- Permission catalog is global (not tenant data): the set of capabilities the
-- system understands. Seeded in 007.
CREATE TABLE IF NOT EXISTS permissions (
    code        TEXT PRIMARY KEY,              -- e.g. memory:read, connector:manage
    description TEXT
);

-- Roles may be system-wide (org_id NULL) or org-custom (org_id set).
CREATE TABLE IF NOT EXISTS roles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    is_system   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_id          UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission_code  TEXT NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_code)
);

-- Binds a principal (user/agent/api_key) to a role within an optional scope
-- (org-wide when scope_type is null, else narrowed to a team/project).
CREATE TABLE IF NOT EXISTS role_bindings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    principal_type  TEXT NOT NULL,             -- user | agent | api_key
    principal_id    UUID NOT NULL,
    role_id         UUID NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    scope_type      TEXT,                      -- NULL=org | team | project
    scope_id        UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, principal_type, principal_id, role_id, scope_type, scope_id)
);
CREATE INDEX IF NOT EXISTS role_bindings_principal_idx
    ON role_bindings (org_id, principal_type, principal_id);
