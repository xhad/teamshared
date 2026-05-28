-- teamshared 001: bootstrap schema for procedural memory and audit.
--
-- The Mem0 schema is owned by Mem0 itself and created automatically the first
-- time the server connects. This file covers everything we own directly:
--
-- * pg_trgm + pg_stat_statements extensions (used by procedure search).
-- * `procedures` table: versioned, agent-callable skills.
-- * `audit_events` table: best-effort log of writes/deletes (`memory_forget`).

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS procedures (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    version         INT  NOT NULL,
    description     TEXT,
    steps_md        TEXT NOT NULL,
    tool_recipe     JSONB,
    tags            TEXT[] NOT NULL DEFAULT '{}',
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE INDEX IF NOT EXISTS procedures_name_idx       ON procedures (name);
CREATE INDEX IF NOT EXISTS procedures_tags_idx       ON procedures USING GIN (tags);
CREATE INDEX IF NOT EXISTS procedures_steps_fts_idx
    ON procedures USING GIN (
        to_tsvector(
            'english',
            coalesce(name, '') || ' ' || coalesce(description, '') || ' ' || coalesce(steps_md, '')
        )
    );

CREATE TABLE IF NOT EXISTS audit_events (
    id            BIGSERIAL PRIMARY KEY,
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    agent         TEXT NOT NULL,
    action        TEXT NOT NULL,          -- 'remember', 'forget', 'procedure_set', ...
    target_id     TEXT,
    payload       JSONB
);
CREATE INDEX IF NOT EXISTS audit_events_agent_idx ON audit_events (agent, occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_action_idx ON audit_events (action, occurred_at DESC);
