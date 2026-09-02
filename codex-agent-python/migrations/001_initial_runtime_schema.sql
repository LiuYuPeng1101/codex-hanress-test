CREATE TABLE conversations (
    id VARCHAR(36) PRIMARY KEY,
    agent_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    runtime_type VARCHAR(64) NOT NULL,
    runtime_thread_id VARCHAR(128) NOT NULL UNIQUE,
    runtime_instance_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_conversations_owner
    ON conversations (tenant_id, user_id, created_at DESC);

CREATE INDEX idx_conversations_runtime_instance
    ON conversations (runtime_instance_id, created_at DESC);

CREATE TABLE approval_requests (
    id VARCHAR(36) PRIMARY KEY,
    conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id),
    requester_user_id VARCHAR(128) NOT NULL,
    tenant_id VARCHAR(128) NOT NULL,
    method VARCHAR(128) NOT NULL,
    thread_id VARCHAR(128),
    turn_id VARCHAR(128),
    server_name VARCHAR(128),
    params JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    decision VARCHAR(32),
    decided_by VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ
);

CREATE INDEX idx_approval_requests_tenant_status_created_at
    ON approval_requests (tenant_id, status, created_at DESC);

CREATE INDEX idx_approval_requests_conversation
    ON approval_requests (conversation_id, created_at DESC);

CREATE INDEX idx_approval_requests_thread_turn
    ON approval_requests (thread_id, turn_id);
