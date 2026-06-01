-- teamshared 004: first-party, tenant-scoped memory store (replaces Mem0).
--
-- Every memory row carries an ``org_id`` real column plus scope/visibility/
-- source/confidence/version/retention metadata. Embeddings live in pgvector
-- columns we own, so retrieval can filter tenant + scope in SQL *before* the
-- vector distance search. This is the core of "isolation by design".

CREATE TABLE IF NOT EXISTS memory_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    pillar              TEXT NOT NULL DEFAULT 'semantic',  -- semantic | episodic
    kind                TEXT NOT NULL DEFAULT 'note',      -- fact|preference|event|note
    scope               TEXT NOT NULL DEFAULT 'org',       -- global|org|team|project|user|agent|conversation|session
    scope_ref_id        UUID,                              -- team/project/user/agent/session id
    visibility          TEXT NOT NULL DEFAULT 'private',   -- private | shared
    content             TEXT NOT NULL,
    summary             TEXT,
    subject             TEXT,
    tags                TEXT[] NOT NULL DEFAULT '{}',
    source              TEXT NOT NULL DEFAULT 'manual',    -- manual|agent|extraction|connector
    source_ref          JSONB,
    confidence          REAL,
    importance          REAL,
    owner_type          TEXT,                              -- user | agent
    owner_id            UUID,
    creator_type        TEXT,                              -- user | agent | api_key
    creator_id          UUID,
    status              TEXT NOT NULL DEFAULT 'active',    -- active|pending_approval|quarantined|soft_deleted
    version             INT NOT NULL DEFAULT 1,
    superseded_by       UUID REFERENCES memory_items(id) ON DELETE SET NULL,
    content_hash        TEXT,
    retention_policy_id UUID,
    expires_at          TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS memory_items_org_idx ON memory_items (org_id);
CREATE INDEX IF NOT EXISTS memory_items_scope_idx ON memory_items (org_id, scope, scope_ref_id);
CREATE INDEX IF NOT EXISTS memory_items_status_idx ON memory_items (org_id, status);
CREATE INDEX IF NOT EXISTS memory_items_tags_idx ON memory_items USING GIN (tags);
CREATE INDEX IF NOT EXISTS memory_items_dedup_idx ON memory_items (org_id, content_hash);
CREATE INDEX IF NOT EXISTS memory_items_fts_idx
    ON memory_items USING GIN (
        to_tsvector('english', coalesce(content, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(subject, ''))
    );

CREATE TABLE IF NOT EXISTS memory_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    memory_id   UUID NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    ordinal     INT NOT NULL DEFAULT 0,
    content     TEXT NOT NULL,
    token_count INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_chunks_org_idx ON memory_chunks (org_id);
CREATE INDEX IF NOT EXISTS memory_chunks_memory_idx ON memory_chunks (memory_id);

-- Embedding dims are pinned to the default embed model (1536). If the embed
-- model changes dimensionality, add a new migration with a new column/table.
CREATE TABLE IF NOT EXISTS memory_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    chunk_id    UUID NOT NULL REFERENCES memory_chunks(id) ON DELETE CASCADE,
    model       TEXT NOT NULL,
    embedding   vector(1536) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS memory_embeddings_org_idx ON memory_embeddings (org_id);
CREATE INDEX IF NOT EXISTS memory_embeddings_hnsw_idx
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS memory_versions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    memory_id   UUID NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    version     INT NOT NULL,
    content     TEXT NOT NULL,
    summary     TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_by  UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (memory_id, version)
);
CREATE INDEX IF NOT EXISTS memory_versions_org_idx ON memory_versions (org_id);

CREATE TABLE IF NOT EXISTS memory_shares (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    memory_id     UUID NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    target_scope  TEXT NOT NULL,               -- team | project | user | agent | org
    target_id     UUID,
    granted_by    UUID,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, memory_id, target_scope, target_id)
);
CREATE INDEX IF NOT EXISTS memory_shares_org_idx ON memory_shares (org_id);
CREATE INDEX IF NOT EXISTS memory_shares_lookup_idx ON memory_shares (org_id, target_scope, target_id);

CREATE TABLE IF NOT EXISTS retention_policies (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    max_age_days  INT,
    max_items     INT,
    kinds         TEXT[] NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS approval_queue (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    memory_id     UUID NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | approved | rejected
    reason        TEXT,
    requested_by  UUID,
    decided_by    UUID,
    decided_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS approval_queue_org_idx ON approval_queue (org_id, status);

-- Bring the pre-existing PoC tables into the tenant model.
ALTER TABLE procedures   ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE procedures   ADD COLUMN IF NOT EXISTS scope TEXT NOT NULL DEFAULT 'org';
CREATE INDEX IF NOT EXISTS procedures_org_idx ON procedures (org_id);

ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS org_id UUID REFERENCES organizations(id) ON DELETE CASCADE;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS actor_type TEXT;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS actor_id UUID;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS resource_type TEXT;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS before JSONB;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS after JSONB;
ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS request_id TEXT;
CREATE INDEX IF NOT EXISTS audit_events_org_idx ON audit_events (org_id, occurred_at DESC);
