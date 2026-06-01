-- teamshared 007: seed the permission catalog and system roles.
--
-- Permissions are the capability vocabulary; system roles are global
-- (org_id NULL) templates bound to principals via role_bindings.

INSERT INTO permissions (code, description) VALUES
    ('memory:create',   'Create memory items'),
    ('memory:read',     'Read/search memory items'),
    ('memory:update',   'Edit memory items'),
    ('memory:delete',   'Delete (soft) memory items'),
    ('memory:approve',  'Approve or reject pending memories'),
    ('memory:share',    'Share memories across scopes'),
    ('memory:export',   'Export memory data'),
    ('memory:admin',    'Administer all memory in the org'),
    ('connector:manage','Connect/sync/disconnect connectors'),
    ('audit:read',      'Read the audit log'),
    ('billing:manage',  'Manage billing'),
    ('org:admin',       'Administer org, members, teams, projects, roles')
ON CONFLICT (code) DO NOTHING;

-- System roles (idempotent).
INSERT INTO roles (id, org_id, name, description, is_system) VALUES
    (gen_random_uuid(), NULL, 'org_owner',           'Full control of the org', TRUE),
    (gen_random_uuid(), NULL, 'org_admin',           'Administer org resources', TRUE),
    (gen_random_uuid(), NULL, 'team_admin',          'Administer a team', TRUE),
    (gen_random_uuid(), NULL, 'project_admin',       'Administer a project', TRUE),
    (gen_random_uuid(), NULL, 'member',              'Standard read/write member', TRUE),
    (gen_random_uuid(), NULL, 'viewer',              'Read-only access', TRUE),
    (gen_random_uuid(), NULL, 'agent',               'Autonomous agent identity', TRUE),
    (gen_random_uuid(), NULL, 'service_account',     'Machine service account', TRUE),
    (gen_random_uuid(), NULL, 'external_collaborator','Limited external access', TRUE)
ON CONFLICT (org_id, name) DO NOTHING;

-- Map system roles to permissions.
WITH role_perm(role_name, perm) AS (
    VALUES
        ('org_owner', 'memory:create'), ('org_owner', 'memory:read'), ('org_owner', 'memory:update'),
        ('org_owner', 'memory:delete'), ('org_owner', 'memory:approve'), ('org_owner', 'memory:share'),
        ('org_owner', 'memory:export'), ('org_owner', 'memory:admin'), ('org_owner', 'connector:manage'),
        ('org_owner', 'audit:read'), ('org_owner', 'billing:manage'), ('org_owner', 'org:admin'),

        ('org_admin', 'memory:create'), ('org_admin', 'memory:read'), ('org_admin', 'memory:update'),
        ('org_admin', 'memory:delete'), ('org_admin', 'memory:approve'), ('org_admin', 'memory:share'),
        ('org_admin', 'memory:export'), ('org_admin', 'memory:admin'), ('org_admin', 'connector:manage'),
        ('org_admin', 'audit:read'), ('org_admin', 'org:admin'),

        ('team_admin', 'memory:create'), ('team_admin', 'memory:read'), ('team_admin', 'memory:update'),
        ('team_admin', 'memory:delete'), ('team_admin', 'memory:approve'), ('team_admin', 'memory:share'),

        ('project_admin', 'memory:create'), ('project_admin', 'memory:read'), ('project_admin', 'memory:update'),
        ('project_admin', 'memory:delete'), ('project_admin', 'memory:approve'), ('project_admin', 'memory:share'),

        ('member', 'memory:create'), ('member', 'memory:read'), ('member', 'memory:update'),
        ('member', 'memory:share'),

        ('viewer', 'memory:read'),

        ('agent', 'memory:create'), ('agent', 'memory:read'),

        ('service_account', 'memory:create'), ('service_account', 'memory:read'),

        ('external_collaborator', 'memory:read')
)
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, rp.perm
FROM role_perm rp
JOIN roles r ON r.name = rp.role_name AND r.org_id IS NULL
ON CONFLICT (role_id, permission_code) DO NOTHING;
