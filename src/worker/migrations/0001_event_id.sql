-- Idempotent baseline: production originally came from schema.sql, while a new
-- Wrangler local database begins empty. Both paths converge here.
CREATE TABLE IF NOT EXISTS messages (
  id          TEXT PRIMARY KEY,
  event_id    TEXT UNIQUE,
  received_at TEXT NOT NULL,
  payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_received ON messages (received_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_event_id ON messages (event_id);
