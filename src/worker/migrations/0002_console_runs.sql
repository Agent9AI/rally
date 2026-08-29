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
  payload      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_console_runs_public_updated
  ON console_runs (public, updated_at DESC);
