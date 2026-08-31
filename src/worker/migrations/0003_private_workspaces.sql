ALTER TABLE console_runs ADD COLUMN workspace_key TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_console_runs_workspace_updated
  ON console_runs (workspace_key, updated_at DESC);
