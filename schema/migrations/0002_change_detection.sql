-- Two-hash change detection, event identity, and disappearance hysteresis.

-- Event identity: (source_id, external_id, event_type, field, old_value,
-- new_value, run_id) hashed into identity_key for idempotent insertion.
-- run_id is part of the key so a legitimate repeated transition (A->B in a
-- later run) is preserved while duplicates within one run/resume are dropped.
ALTER TABLE events ADD COLUMN source_id TEXT;
ALTER TABLE events ADD COLUMN external_id TEXT;
ALTER TABLE events ADD COLUMN field TEXT;
ALTER TABLE events ADD COLUMN old_value TEXT;
ALTER TABLE events ADD COLUMN new_value TEXT;
ALTER TABLE events ADD COLUMN run_id TEXT;
ALTER TABLE events ADD COLUMN identity_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_event_identity
  ON events(identity_key) WHERE identity_key IS NOT NULL;

-- raw_sha256: hash of the exact fetched payload (storage integrity / parser-
-- upgrade suppression). The existing record_hash/content_hash columns hold
-- the canonical hash. parser_version 0 marks rows written before versioning.
ALTER TABLE clinical_trials ADD COLUMN raw_sha256 TEXT NOT NULL DEFAULT '';
ALTER TABLE clinical_trials ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE clinical_trials ADD COLUMN miss_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE regulatory_documents ADD COLUMN raw_sha256 TEXT NOT NULL DEFAULT '';
ALTER TABLE regulatory_documents ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 0;
ALTER TABLE company_documents ADD COLUMN raw_sha256 TEXT NOT NULL DEFAULT '';
ALTER TABLE company_documents ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 0;

ALTER TABLE clinical_trial_snapshots ADD COLUMN raw_sha256 TEXT;
ALTER TABLE clinical_trial_snapshots ADD COLUMN parser_version INTEGER;
ALTER TABLE regulatory_document_snapshots ADD COLUMN raw_sha256 TEXT;
ALTER TABLE regulatory_document_snapshots ADD COLUMN parser_version INTEGER;
ALTER TABLE company_document_snapshots ADD COLUMN raw_sha256 TEXT;
ALTER TABLE company_document_snapshots ADD COLUMN parser_version INTEGER;
