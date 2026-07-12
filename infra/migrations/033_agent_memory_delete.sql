-- teamshared 033: let agent tokens soft-delete memories (memory_forget).
--
-- memory_forget_skill and memory_forget_procedure have always been available
-- to agent principals (audited, soft-delete). memory_forget was the odd one
-- out: it requires memory:delete, which only admin-tier roles held, so an
-- agent could create a memory but never retract it — bad writes accumulated.
-- Grant memory:delete to the agent and service_account system roles; every
-- delete remains a soft-delete with a required audit reason.

WITH role_perm(role_name, perm) AS (
    VALUES
        ('agent', 'memory:delete'),
        ('service_account', 'memory:delete')
)
INSERT INTO role_permissions (role_id, permission_code)
SELECT r.id, rp.perm
FROM role_perm rp
JOIN roles r ON r.name = rp.role_name AND r.org_id IS NULL
ON CONFLICT (role_id, permission_code) DO NOTHING;
