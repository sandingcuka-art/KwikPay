BEGIN;
CREATE TABLE IF NOT EXISTS open_payments_evidence (
    execution_id TEXT NOT NULL,
    leg_id TEXT NOT NULL,
    sent_value TEXT NOT NULL,
    received_value TEXT NOT NULL,
    observed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    PRIMARY KEY (execution_id, leg_id),
    FOREIGN KEY (execution_id, leg_id) REFERENCES provider_legs(execution_id, leg_id)
);
INSERT OR IGNORE INTO schema_migrations (version) VALUES (6);
COMMIT;
