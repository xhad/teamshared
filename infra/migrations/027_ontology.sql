-- teamshared 027: Org ontology — link types, object kinds, interfaces, action types, action log.

CREATE TABLE IF NOT EXISTS ontology_link_types (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    from_kinds  TEXT[] NOT NULL DEFAULT '{}',
    to_kinds    TEXT[] NOT NULL DEFAULT '{}',
    cardinality TEXT NOT NULL DEFAULT 'many_to_many',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS ontology_object_kinds (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    description       TEXT,
    properties_schema JSONB NOT NULL DEFAULT '{}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS ontology_interfaces (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    traits      JSONB NOT NULL DEFAULT '[]',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS ontology_kind_interfaces (
    org_id       UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind_id      UUID NOT NULL REFERENCES ontology_object_kinds(id) ON DELETE CASCADE,
    interface_id UUID NOT NULL REFERENCES ontology_interfaces(id) ON DELETE CASCADE,
    PRIMARY KEY (org_id, kind_id, interface_id)
);

CREATE TABLE IF NOT EXISTS ontology_entities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    kind_id     UUID NOT NULL REFERENCES ontology_object_kinds(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL,
    properties  JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'pending_approval', 'rejected')),
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, slug)
);

CREATE TABLE IF NOT EXISTS ontology_action_types (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name              TEXT NOT NULL,
    description       TEXT,
    wrapper_tool      TEXT NOT NULL,
    parameters_schema JSONB NOT NULL DEFAULT '{}',
    requires_approval BOOLEAN NOT NULL DEFAULT false,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, name)
);

CREATE TABLE IF NOT EXISTS ontology_action_log (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    action_type_id UUID NOT NULL REFERENCES ontology_action_types(id) ON DELETE CASCADE,
    parameters     JSONB NOT NULL DEFAULT '{}',
    result         JSONB,
    status         TEXT NOT NULL
        CHECK (status IN ('applied', 'rejected', 'failed')),
    actor          TEXT,
    request_id     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ontology_entities_org_slug_idx
    ON ontology_entities (org_id, slug);

CREATE INDEX IF NOT EXISTS ontology_action_log_org_created_idx
    ON ontology_action_log (org_id, created_at DESC);

ALTER TABLE ontology_link_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_link_types FORCE ROW LEVEL SECURITY;
ALTER TABLE ontology_object_kinds ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_object_kinds FORCE ROW LEVEL SECURITY;
ALTER TABLE ontology_interfaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_interfaces FORCE ROW LEVEL SECURITY;
ALTER TABLE ontology_kind_interfaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_kind_interfaces FORCE ROW LEVEL SECURITY;
ALTER TABLE ontology_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_entities FORCE ROW LEVEL SECURITY;
ALTER TABLE ontology_action_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_action_types FORCE ROW LEVEL SECURITY;
ALTER TABLE ontology_action_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE ontology_action_log FORCE ROW LEVEL SECURITY;

CREATE POLICY ontology_link_types_org ON ontology_link_types
    USING (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);

CREATE POLICY ontology_object_kinds_org ON ontology_object_kinds
    USING (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);

CREATE POLICY ontology_interfaces_org ON ontology_interfaces
    USING (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);

CREATE POLICY ontology_kind_interfaces_org ON ontology_kind_interfaces
    USING (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);

CREATE POLICY ontology_entities_org ON ontology_entities
    USING (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);

CREATE POLICY ontology_action_types_org ON ontology_action_types
    USING (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);

CREATE POLICY ontology_action_log_org ON ontology_action_log
    USING (org_id = current_setting('app.org_id', true)::uuid)
    WITH CHECK (org_id = current_setting('app.org_id', true)::uuid);
