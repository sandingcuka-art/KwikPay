BEGIN;
CREATE TABLE IF NOT EXISTS incoming_payment_evidence (
    execution_id TEXT NOT NULL,
    leg_id TEXT NOT NULL,
    incoming_url TEXT NOT NULL,
    completed INTEGER NOT NULL CHECK (completed IN (0, 1)),
    received_value TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (execution_id, leg_id),
    FOREIGN KEY (execution_id, leg_id) REFERENCES provider_legs(execution_id, leg_id)
);
INSERT OR IGNORE INTO schema_migrations (version) VALUES (7);
COMMIT;
