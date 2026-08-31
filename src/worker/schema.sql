-- Rally ingress inbox.
-- D1 rather than KV: this is a queue that is polled and must be read-your-writes.
-- KV list is eventually consistent, so a freshly delivered commission was
-- invisible to the runner for up to a minute. Measured, not assumed.
CREATE TABLE IF NOT EXISTS messages (
  id          TEXT PRIMARY KEY,
  event_id    TEXT UNIQUE NOT NULL,
  received_at TEXT NOT NULL,
  payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_received ON messages (received_at);

-- Judge-visible console records are a separate, explicitly public projection.
-- The source runner and Worker both allowlist fields before this payload lands.
CREATE TABLE IF NOT EXISTS console_runs (
  run_id       TEXT PRIMARY KEY,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('running', 'complete', 'blocked', 'halted')),
  title        TEXT NOT NULL,
  turn         INTEGER NOT NULL DEFAULT 0 CHECK (turn >= 0),
  done_items   INTEGER NOT NULL DEFAULT 0 CHECK (done_items >= 0),
  total_items  INTEGER NOT NULL DEFAULT 0 CHECK (total_items >= 0),
  public       INTEGER NOT NULL DEFAULT 0 CHECK (public IN (0, 1)),
  workspace_key TEXT NOT NULL DEFAULT '',
  payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_console_runs_public_updated
  ON console_runs (public, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_console_runs_workspace_updated
  ON console_runs (workspace_key, updated_at DESC);
