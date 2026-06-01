-- teamshared 005: connector framework tables.
--
-- Connectors ingest from external systems (Slack, GitHub, Notion, Drive,
-- Linear, MCP servers). OAuth tokens are stored encrypted at rest
-- (envelope encryption); only ciphertext + nonce + key id live in the DB.

CREATE TABLE IF NOT EXISTS connectors (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,                  -- slack|github|notion|gdrive|linear|mcp
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'disconnected',  -- disconnected|connected|error
    config      JSONB NOT NULL DEFAULT '{}',
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, kind, name)
);
CREATE INDEX IF NOT EXISTS connectors_org_idx ON connectors (org_id);

CREATE TABLE IF NOT EXISTS connector_tokens (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    connector_id  UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    ciphertext    BYTEA NOT NULL,
    nonce         BYTEA NOT NULL,
    key_id        TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at    TIMESTAMPTZ,
    UNIQUE (connector_id)
);
CREATE INDEX IF NOT EXISTS connector_tokens_org_idx ON connector_tokens (org_id);

CREATE TABLE IF NOT EXISTS connector_sync_state (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    connector_id   UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    cursor         TEXT,
    last_synced_at TIMESTAMPTZ,
    status         TEXT NOT NULL DEFAULT 'idle',  -- idle|running|error
    error          TEXT,
    UNIQUE (connector_id)
);
CREATE INDEX IF NOT EXISTS connector_sync_state_org_idx ON connector_sync_state (org_id);

CREATE TABLE IF NOT EXISTS source_documents (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    connector_id  UUID NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    external_id   TEXT NOT NULL,
    uri           TEXT,
    checksum      TEXT,
    acl           JSONB NOT NULL DEFAULT '{}',   -- mirrored source permissions
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at    TIMESTAMPTZ,
    UNIQUE (org_id, connector_id, external_id)
);
CREATE INDEX IF NOT EXISTS source_documents_org_idx ON source_documents (org_id);
