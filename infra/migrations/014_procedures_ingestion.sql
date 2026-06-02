-- Procedure ingestion: status gating + approval-queue linkage.

ALTER TABLE procedures
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';

CREATE INDEX IF NOT EXISTS procedures_org_status_idx
    ON procedures (org_id, status);

ALTER TABLE approval_queue
    ALTER COLUMN memory_id DROP NOT NULL;

ALTER TABLE approval_queue
    ADD COLUMN IF NOT EXISTS procedure_id BIGINT REFERENCES procedures(id) ON DELETE CASCADE;

ALTER TABLE approval_queue
    DROP CONSTRAINT IF EXISTS approval_queue_target_check;

ALTER TABLE approval_queue
    ADD CONSTRAINT approval_queue_target_check CHECK (
        (memory_id IS NOT NULL AND procedure_id IS NULL)
        OR (memory_id IS NULL AND procedure_id IS NOT NULL)
    );
