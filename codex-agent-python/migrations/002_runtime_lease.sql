ALTER TABLE conversations
    ADD COLUMN runtime_lease_owner VARCHAR(128),
    ADD COLUMN runtime_lease_expires_at TIMESTAMPTZ,
    ADD COLUMN runtime_generation BIGINT;

UPDATE conversations
SET runtime_lease_owner = runtime_instance_id,
    runtime_lease_expires_at = NOW(),
    runtime_generation = 1
WHERE runtime_lease_owner IS NULL;

ALTER TABLE conversations
    ALTER COLUMN runtime_lease_owner SET NOT NULL,
    ALTER COLUMN runtime_lease_expires_at SET NOT NULL,
    ALTER COLUMN runtime_generation SET NOT NULL;

CREATE INDEX idx_conversations_runtime_lease
    ON conversations (runtime_lease_owner, runtime_lease_expires_at);
