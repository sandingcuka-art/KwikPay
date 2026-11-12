BEGIN;
CREATE TABLE IF NOT EXISTS payment_diagnostics (
    id INTEGER PRIMARY KEY,
    execution_id TEXT NOT NULL REFERENCES execution_records(id),
    leg_id TEXT,
    operation TEXT NOT NULL,
    outcome TEXT NOT NULL,
    provider_status INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
INSERT OR IGNORE INTO schema_migrations (version) VALUES (5);
COMMIT;
