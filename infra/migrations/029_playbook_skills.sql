-- teamshared 029: playbooks as ordered skill collections (tool_recipe.skills).
--
-- steps_md holds optional intro/context; skill bodies resolve at runtime via
-- expand_playbook_skills. Workflows remain procedures whose tool_recipe has stages.

CREATE INDEX IF NOT EXISTS procedures_playbook_skills_idx
    ON procedures USING GIN ((tool_recipe -> 'skills'))
    WHERE status = 'active' AND tool_recipe ? 'skills';
