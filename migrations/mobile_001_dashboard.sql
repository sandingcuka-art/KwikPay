ALTER TABLE mobile_requests ADD COLUMN snapshot_json TEXT;
CREATE TABLE mobile_config (id INTEGER PRIMARY KEY CHECK(id = 1), version INTEGER NOT NULL, pots_json TEXT NOT NULL);
