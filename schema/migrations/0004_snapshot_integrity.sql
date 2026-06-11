-- Content-addressed raw payload storage + enforced snapshot immutability.

CREATE TABLE IF NOT EXISTS raw_blobs (
  raw_sha256 TEXT PRIMARY KEY,
  content    BLOB NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Snapshots and blobs are immutable: enforced, not promised.
CREATE TRIGGER IF NOT EXISTS clinical_trial_snapshots_no_update
  BEFORE UPDATE ON clinical_trial_snapshots
  BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS clinical_trial_snapshots_no_delete
  BEFORE DELETE ON clinical_trial_snapshots
  BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;

CREATE TRIGGER IF NOT EXISTS regulatory_document_snapshots_no_update
  BEFORE UPDATE ON regulatory_document_snapshots
  BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS regulatory_document_snapshots_no_delete
  BEFORE DELETE ON regulatory_document_snapshots
  BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;

CREATE TRIGGER IF NOT EXISTS company_document_snapshots_no_update
  BEFORE UPDATE ON company_document_snapshots
  BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
CREATE TRIGGER IF NOT EXISTS company_document_snapshots_no_delete
  BEFORE DELETE ON company_document_snapshots
  BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;

CREATE TRIGGER IF NOT EXISTS raw_blobs_no_update
  BEFORE UPDATE ON raw_blobs
  BEGIN SELECT RAISE(ABORT, 'raw blobs are immutable'); END;
CREATE TRIGGER IF NOT EXISTS raw_blobs_no_delete
  BEFORE DELETE ON raw_blobs
  BEGIN SELECT RAISE(ABORT, 'raw blobs are immutable'); END;
