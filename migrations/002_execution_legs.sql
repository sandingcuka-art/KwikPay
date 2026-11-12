BEGIN;
CREATE TABLE IF NOT EXISTS execution_legs (
    execution_id TEXT NOT NULL REFERENCES execution_records(id),
    leg_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'PREPARED', 'PROCESSING', 'COMPLETED', 'FAILED')),
    PRIMARY KEY (execution_id, leg_id)
);
INSERT OR IGNORE INTO execution_legs (execution_id, leg_id, status)
SELECT execution_records.id, json_extract(legs.value, '$.id'), 'PENDING'
FROM execution_records, json_each(execution_records.plan_json, '$.legs') AS legs;
INSERT OR IGNORE INTO schema_migrations (version) VALUES (2);
COMMIT;
