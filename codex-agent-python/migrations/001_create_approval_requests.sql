CREATE TABLE IF NOT EXISTS approval_requests (
    id VARCHAR(36) PRIMARY KEY,
    method VARCHAR(128) NOT NULL,
    params JSONB NOT NULL,
    status VARCHAR(32) NOT NULL,
    decision VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL,
    decided_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_approval_requests_status_created_at
    ON approval_requests (status, created_at DESC);
