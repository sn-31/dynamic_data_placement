-- Schema for AI-Driven Dynamic Data Placement System

CREATE TABLE IF NOT EXISTS storage_nodes (
    node_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    tier VARCHAR(20) NOT NULL, -- 'hot', 'warm', 'cold'
    capacity_bytes BIGINT NOT NULL,
    used_bytes BIGINT DEFAULT 0,
    base_latency_ms FLOAT NOT NULL DEFAULT 10.0,
    status VARCHAR(20) DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS files (
    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename VARCHAR(255) NOT NULL UNIQUE,
    file_size BIGINT NOT NULL,
    current_node_id VARCHAR(50) REFERENCES storage_nodes(node_id),
    predicted_popularity VARCHAR(20) DEFAULT 'unclassified', -- set by the ML model after inference
    placement_policy VARCHAR(50) DEFAULT 'static',   -- 'static', 'heuristic', 'ml'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    access_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS access_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    response_time_ms FLOAT NOT NULL,
    node_id VARCHAR(50) REFERENCES storage_nodes(node_id),
    access_type VARCHAR(20) DEFAULT 'read'
);

CREATE TABLE IF NOT EXISTS placement_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL REFERENCES files(file_id) ON DELETE CASCADE,
    from_node_id VARCHAR(50),
    to_node_id VARCHAR(50) NOT NULL,
    reason VARCHAR(255),
    policy_used VARCHAR(50) NOT NULL,
    migrated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_files_node ON files(current_node_id);
CREATE INDEX IF NOT EXISTS idx_logs_file ON access_logs(file_id);
CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON access_logs(accessed_at);
