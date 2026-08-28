-- Rally ingress inbox.
-- D1 rather than KV: this is a queue that is polled and must be read-your-writes.
-- KV list is eventually consistent, so a freshly delivered commission was
-- invisible to the runner for up to a minute. Measured, not assumed.
CREATE TABLE IF NOT EXISTS messages (
  id          TEXT PRIMARY KEY,
  received_at TEXT NOT NULL,
  payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_received ON messages (received_at);
