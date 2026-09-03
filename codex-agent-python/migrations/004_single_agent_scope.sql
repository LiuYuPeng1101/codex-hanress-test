-- 单 Agent 模式不需要 Agent Registry / Runtime Router / Lease 元数据。
-- 保留 conversation_id -> Codex runtime_thread_id，以及用户/租户所有权。
DROP INDEX IF EXISTS idx_conversations_runtime_instance;
DROP INDEX IF EXISTS idx_conversations_runtime_lease;

ALTER TABLE conversations
    DROP COLUMN IF EXISTS agent_id,
    DROP COLUMN IF EXISTS runtime_type,
    DROP COLUMN IF EXISTS runtime_instance_id,
    DROP COLUMN IF EXISTS runtime_lease_owner,
    DROP COLUMN IF EXISTS runtime_lease_expires_at,
    DROP COLUMN IF EXISTS runtime_generation;
