-- Org-scoped graph edges in Postgres (Neo4j-free fallback for autolink + traversal).

CREATE TABLE IF NOT EXISTS memory_graph_edges (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    subject     TEXT NOT NULL,
    predicate   TEXT NOT NULL,
    object      TEXT NOT NULL,
    weight      DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, subject, predicate, object)
);

CREATE INDEX IF NOT EXISTS memory_graph_edges_org_subject_idx
    ON memory_graph_edges (org_id, lower(subject));

CREATE INDEX IF NOT EXISTS memory_graph_edges_org_object_idx
    ON memory_graph_edges (org_id, lower(object));

ALTER TABLE memory_graph_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE memory_graph_edges FORCE ROW LEVEL SECURITY;

CREATE POLICY memory_graph_edges_org ON memory_graph_edges
    USING (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);
