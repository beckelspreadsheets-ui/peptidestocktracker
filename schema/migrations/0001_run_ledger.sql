-- Run ledger: every scan is a tracked run with per-source task state.
CREATE TABLE IF NOT EXISTS runs (
  run_id       TEXT PRIMARY KEY,        -- UTC-timestamp-prefixed, sortable
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status       TEXT NOT NULL CHECK (status IN ('running','completed','interrupted','failed')),
  summary_json TEXT
);

CREATE TABLE IF NOT EXISTS run_tasks (
  run_id      TEXT NOT NULL REFERENCES runs(run_id),
  source_id   TEXT NOT NULL,
  status      TEXT NOT NULL CHECK (status IN ('pending','running','done','error','skipped')),
  attempt     INTEGER NOT NULL DEFAULT 0,
  error       TEXT,
  counts_json TEXT,
  started_at  TEXT,
  finished_at TEXT,
  PRIMARY KEY (run_id, source_id)
);

CREATE TABLE IF NOT EXISTS source_cursors (
  source_id     TEXT PRIMARY KEY,
  etag          TEXT,
  last_modified TEXT,
  cursor_json   TEXT,
  updated_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_run_tasks_source ON run_tasks(source_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
