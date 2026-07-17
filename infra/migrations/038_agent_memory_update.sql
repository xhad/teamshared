-- teamshared 038: grant memory:update to agent + service_account roles.
--
-- The agent system role (007) was seeded with only memory:create + memory:read,
-- and later gained memory:delete — but not memory:update. That left agents able
-- to create and delete shared files but unable to update/publish/unpublish them
-- (file_update / file_publish / file_unpublish all require memory:update). Add
-- memory:update so agents can manage the full shared-file lifecycle. API keys
-- carry no scope narrowing (scopes=[]), so the role grant is effective
-- immediately — the Authorizer is built fresh per request, no restart needed.

WITH role_perm(role_name, perm) AS (
    VALUES
        ('agent',           'memory:update'),
        ('service_account', 'memory:update')
)
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, rp.perm
FROM role_perm rp
JOIN roles r ON r.name = rp.role_name AND r.org_id IS NULL
ON CONFLICT (role_id, permission_code) DO NOTHING;
