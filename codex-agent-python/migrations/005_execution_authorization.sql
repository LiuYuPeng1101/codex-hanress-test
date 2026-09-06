-- Structured business grants are distinct from legacy SDK approval messages.
-- Do not backfill execution IDs: historical approvals were not bound to this contract.
ALTER TABLE approval_requests
    ADD COLUMN execution_id VARCHAR(36),
    ADD COLUMN operation VARCHAR(128),
    ADD COLUMN operation_arguments JSONB,
    ADD COLUMN expires_at TIMESTAMPTZ;

ALTER TABLE approval_requests ADD CONSTRAINT ck_execution_grant_complete CHECK (
    (execution_id IS NULL AND operation IS NULL AND operation_arguments IS NULL AND expires_at IS NULL)
    OR
    (execution_id IS NOT NULL AND operation IS NOT NULL AND operation_arguments IS NOT NULL
        AND expires_at IS NOT NULL)
);
CREATE UNIQUE INDEX uq_execution_grant_id ON approval_requests(execution_id)
    WHERE execution_id IS NOT NULL;
-- Keep terminal grants in the uniqueness scope. A rejected/expired/uncertain action
-- must not silently generate a fresh idempotency key when the model retries.
CREATE UNIQUE INDEX uq_execution_grant_action ON approval_requests(conversation_id, approval_key)
    WHERE execution_id IS NOT NULL;
