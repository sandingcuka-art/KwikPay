BEGIN;
CREATE TABLE IF NOT EXISTS provider_legs (
    execution_id TEXT NOT NULL,
    leg_id TEXT NOT NULL,
    outgoing_url TEXT,
    received_value TEXT,
    PRIMARY KEY (execution_id, leg_id),
    FOREIGN KEY (execution_id, leg_id) REFERENCES execution_legs(execution_id, leg_id)
);
INSERT OR IGNORE INTO schema_migrations (version) VALUES (3);
COMMIT;
