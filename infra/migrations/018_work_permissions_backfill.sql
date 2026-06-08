-- teamshared 018: backfill work permissions and membership role bindings.
--
-- Orgs provisioned before 016 may lack work:* on system roles, and some
-- console users have a memberships.role but no matching role_bindings row.

INSERT INTO permissions (code, description) VALUES
    ('work:read',  'List and view work items'),
    ('work:write', 'Create and update work items')
ON CONFLICT (code) DO NOTHING;

WITH role_perm(role_name, perm) AS (
    VALUES
        ('org_owner', 'work:read'), ('org_owner', 'work:write'),
        ('org_admin', 'work:read'), ('org_admin', 'work:write'),
        ('team_admin', 'work:read'), ('team_admin', 'work:write'),
        ('project_admin', 'work:read'), ('project_admin', 'work:write'),
        ('member', 'work:read'), ('member', 'work:write'),
        ('viewer', 'work:read'),
        ('agent', 'work:read'), ('agent', 'work:write'),
        ('service_account', 'work:read'), ('service_account', 'work:write')
)
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, rp.perm
FROM role_perm rp
JOIN roles r ON r.name = rp.role_name AND r.org_id IS NULL
ON CONFLICT (role_id, permission_code) DO NOTHING;

INSERT INTO role_bindings (org_id, principal_type, principal_id, role_id)
SELECT m.org_id, 'user', m.user_id, r.id
FROM memberships m
JOIN roles r ON r.name = m.role AND r.org_id IS NULL AND r.is_system
WHERE NOT EXISTS (
    SELECT 1
    FROM role_bindings rb
    WHERE rb.org_id = m.org_id
      AND rb.principal_type = 'user'
      AND rb.principal_id = m.user_id
      AND rb.scope_type IS NULL
      AND rb.scope_id IS NULL
);
