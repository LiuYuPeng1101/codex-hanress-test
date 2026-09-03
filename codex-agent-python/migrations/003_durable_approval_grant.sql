ALTER TABLE approval_requests
    ADD COLUMN approval_key VARCHAR(64),
    ADD COLUMN consumed_at TIMESTAMPTZ;

-- 历史审批没有可安全重放的稳定业务指纹，迁移时使用记录 ID 作为不可复用 key。
UPDATE approval_requests
SET approval_key = id
WHERE approval_key IS NULL;

ALTER TABLE approval_requests
    ALTER COLUMN approval_key SET NOT NULL;

CREATE INDEX idx_approval_requests_action_key
    ON approval_requests (conversation_id, approval_key, created_at DESC);

CREATE UNIQUE INDEX uq_approval_requests_active_grant
    ON approval_requests (conversation_id, approval_key)
    WHERE status IN ('PENDING', 'APPROVED');
