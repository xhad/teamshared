-- teamshared 026: copy atomic procedures into skills (misclassified SKILL.md content).
--
-- Skips workflow definitions (tool_recipe.stages) and composed playbooks
-- (tool_recipe.skills). Retires migrated procedures via soft_deleted.

INSERT INTO skills (
    org_id, scope, name, version, description, body_md, tool_hints,
    tags, created_by, created_at, status
)
SELECT
    p.org_id,
    p.scope,
    p.name,
    p.version,
    p.description,
    p.steps_md,
    CASE
        WHEN p.tool_recipe IS NULL THEN NULL
        WHEN p.tool_recipe ? 'stages' OR p.tool_recipe ? 'skills' THEN NULL
        ELSE p.tool_recipe
    END,
    CASE
        WHEN 'migrated-from-procedure' = ANY (p.tags) THEN p.tags
        ELSE array_append(p.tags, 'migrated-from-procedure')
    END,
    p.created_by,
    p.created_at,
    'active'
FROM procedures p
WHERE p.status = 'active'
  AND NOT (COALESCE(p.tool_recipe, '{}'::jsonb) ? 'stages')
  AND NOT (COALESCE(p.tool_recipe, '{}'::jsonb) ? 'skills')
ON CONFLICT (org_id, name, version) DO NOTHING;

UPDATE procedures p
SET status = 'soft_deleted'
WHERE p.status = 'active'
  AND NOT (COALESCE(p.tool_recipe, '{}'::jsonb) ? 'stages')
  AND NOT (COALESCE(p.tool_recipe, '{}'::jsonb) ? 'skills')
  AND EXISTS (
      SELECT 1 FROM skills s
      WHERE s.org_id = p.org_id
        AND s.name = p.name
        AND s.version = p.version
        AND s.status = 'active'
  );
