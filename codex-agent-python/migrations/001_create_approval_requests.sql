CREATE TABLE approval_requests (
    id VARCHAR(36) PRIMARY KEY,
    method VARCHAR(128) NOT NULL,
    thread_id VARCHAR(128),
    turn_id VARCHAR(128),
    server_name VARCHAR(128),
    params JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    decision VARCHAR(32),
    decided_by VARCHAR(128),
    decided_tenant_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ
);

CREATE INDEX idx_approval_requests_status_created_at
    ON approval_requests (status, created_at DESC);

CREATE INDEX idx_approval_requests_thread_turn
    ON approval_requests (thread_id, turn_id);
