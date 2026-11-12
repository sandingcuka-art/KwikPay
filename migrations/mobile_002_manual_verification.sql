CREATE TABLE manual_verification_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  execution_id TEXT NOT NULL,
  leg_id TEXT NOT NULL,
  verified INTEGER NOT NULL CHECK (verified IN (0, 1)),
  recorded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  actor TEXT NOT NULL DEFAULT 'merchant',
  FOREIGN KEY (execution_id, leg_id) REFERENCES execution_legs(execution_id, leg_id)
);
CREATE INDEX manual_verification_leg ON manual_verification_events(execution_id, leg_id, id);
