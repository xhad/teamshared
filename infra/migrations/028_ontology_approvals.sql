-- teamshared 028: ontology entity approvals in the shared approval queue.

ALTER TABLE approval_queue
    ADD COLUMN IF NOT EXISTS ontology_entity_id UUID
        REFERENCES ontology_entities(id) ON DELETE CASCADE;

ALTER TABLE approval_queue
    DROP CONSTRAINT IF EXISTS approval_queue_target_check;

ALTER TABLE approval_queue
    ADD CONSTRAINT approval_queue_target_check CHECK (
        (memory_id IS NOT NULL AND procedure_id IS NULL AND skill_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL AND ontology_entity_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NOT NULL AND skill_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL AND ontology_entity_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL AND skill_id IS NOT NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL AND ontology_entity_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL AND skill_id IS NULL
            AND strategic_entity_type IS NOT NULL AND strategic_entity_id IS NOT NULL
            AND work_item_id IS NULL AND ontology_entity_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL AND skill_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NOT NULL AND ontology_entity_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NULL AND skill_id IS NULL
            AND strategic_entity_type IS NULL AND strategic_entity_id IS NULL
            AND work_item_id IS NULL AND ontology_entity_id IS NOT NULL)
    );
