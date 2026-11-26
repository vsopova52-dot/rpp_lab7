CREATE TABLE IF NOT EXISTS counters (
    name VARCHAR(100) PRIMARY KEY,
    value BIGINT NOT NULL DEFAULT 0
);

INSERT INTO counters (name, value)
VALUES ('visits', 0)
ON CONFLICT (name) DO NOTHING;

CREATE TABLE IF NOT EXISTS job_runs (
    slot BIGINT PRIMARY KEY,
    instance_id VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL
);
