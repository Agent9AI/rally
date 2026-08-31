-- Dashboard-created work needs a reload-persistent projection while it waits
-- for the runner. This is deliberately separate from console_runs: "queued"
-- is an intake state, not an authoritative runner lifecycle status.
CREATE TABLE IF NOT EXISTS workspace_jobs (
  run_id              TEXT PRIMARY KEY,
  workspace_key       TEXT NOT NULL,
  event_id            TEXT UNIQUE NOT NULL,
  request_fingerprint TEXT NOT NULL,
  title               TEXT NOT NULL,
  created_at          TEXT NOT NULL,
  updated_at          TEXT NOT NULL,
  source_run_id       TEXT,
  superseded_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_workspace_jobs_workspace_queued
  ON workspace_jobs (workspace_key, superseded_at, updated_at DESC);
