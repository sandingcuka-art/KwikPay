BEGIN;
CREATE TABLE IF NOT EXISTS test_wallet_sessions (
    execution_id TEXT PRIMARY KEY REFERENCES execution_records(id),
    state TEXT NOT NULL,
    quotes_json TEXT,
    debit_minor TEXT,
    auth_server TEXT,
    nonce TEXT,
    pending_json TEXT,
    grant_json TEXT
);
INSERT OR IGNORE INTO schema_migrations (version) VALUES (4);
COMMIT;
