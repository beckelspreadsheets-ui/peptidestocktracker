CREATE TABLE IF NOT EXISTS peptides (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  primary_target INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS peptide_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  peptide_id TEXT NOT NULL REFERENCES peptides(id),
  alias TEXT NOT NULL,
  UNIQUE(peptide_id, alias)
);

CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  public_private TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS securities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  company_id INTEGER REFERENCES companies(id),
  ticker TEXT,
  exchange TEXT,
  country TEXT,
  liquidity_risk TEXT,
  dilution_risk TEXT,
  UNIQUE(ticker, exchange)
);

CREATE TABLE IF NOT EXISTS clinical_trials (
  nct_id TEXT PRIMARY KEY,
  source_url TEXT NOT NULL,
  brief_title TEXT,
  official_title TEXT,
  overall_status TEXT,
  phase TEXT,
  phases_json TEXT NOT NULL DEFAULT '[]',
  enrollment_count INTEGER,
  enrollment_type TEXT,
  sponsor_name TEXT,
  primary_completion_date TEXT,
  completion_date TEXT,
  last_update_post_date TEXT,
  has_results INTEGER NOT NULL DEFAULT 0,
  interventions_json TEXT NOT NULL DEFAULT '[]',
  conditions_json TEXT NOT NULL DEFAULT '[]',
  primary_outcomes_json TEXT NOT NULL DEFAULT '[]',
  locations_json TEXT NOT NULL DEFAULT '[]',
  peptide_ids_json TEXT NOT NULL DEFAULT '[]',
  matched_aliases_json TEXT NOT NULL DEFAULT '[]',
  query_terms_json TEXT NOT NULL DEFAULT '[]',
  record_hash TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS clinical_trial_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nct_id TEXT NOT NULL REFERENCES clinical_trials(nct_id),
  record_hash TEXT NOT NULL,
  captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  source_url TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  UNIQUE(nct_id, record_hash)
);

CREATE TABLE IF NOT EXISTS regulatory_documents (
  document_key TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  document_number TEXT,
  publication_date TEXT,
  docket_ids_json TEXT NOT NULL DEFAULT '[]',
  content_hash TEXT NOT NULL,
  content_text TEXT NOT NULL,
  peptide_ids_json TEXT NOT NULL DEFAULT '[]',
  matched_aliases_json TEXT NOT NULL DEFAULT '[]',
  route_notes_json TEXT NOT NULL DEFAULT '{}',
  status_terms_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS regulatory_document_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_key TEXT NOT NULL REFERENCES regulatory_documents(document_key),
  content_hash TEXT NOT NULL,
  captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  url TEXT NOT NULL,
  content_text TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(document_key, content_hash)
);

CREATE TABLE IF NOT EXISTS company_documents (
  document_key TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  company_key TEXT,
  company_name TEXT,
  ticker TEXT,
  exchange TEXT,
  filing_type TEXT,
  accession_number TEXT,
  filing_date TEXT,
  source_tier TEXT,
  content_hash TEXT NOT NULL,
  content_text TEXT NOT NULL,
  peptide_ids_json TEXT NOT NULL DEFAULT '[]',
  matched_aliases_json TEXT NOT NULL DEFAULT '[]',
  company_matches_json TEXT NOT NULL DEFAULT '[]',
  keyword_matches_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS company_document_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_key TEXT NOT NULL REFERENCES company_documents(document_key),
  content_hash TEXT NOT NULL,
  captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  url TEXT NOT NULL,
  content_text TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(document_key, content_hash)
);

CREATE TABLE IF NOT EXISTS source_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT,
  retrieved_at TEXT NOT NULL,
  content_hash TEXT,
  evidence_tier TEXT,
  raw_path TEXT
);

CREATE TABLE IF NOT EXISTS claims (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claim_hash TEXT,
  claim_text TEXT NOT NULL,
  entity_name TEXT,
  company_name TEXT,
  peptide_id TEXT,
  claim_category TEXT,
  source_type TEXT NOT NULL DEFAULT 'external_report',
  source_label TEXT,
  source_url TEXT,
  target_status TEXT,
  status TEXT NOT NULL DEFAULT 'needs_verification',
  confidence TEXT NOT NULL DEFAULT 'low',
  priority TEXT,
  verification_path TEXT,
  evidence_excerpt TEXT,
  reviewer_notes TEXT,
  first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_checked_at TEXT,
  needs_review INTEGER NOT NULL DEFAULT 1,
  imported_from TEXT,
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  peptide_id TEXT,
  company_id INTEGER,
  source_document_id INTEGER REFERENCES source_documents(id),
  title TEXT NOT NULL,
  what_changed TEXT,
  why_it_matters TEXT,
  confidence TEXT,
  severity TEXT,
  directness TEXT,
  stock_market_relevance TEXT,
  needs_review INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER REFERENCES events(id),
  channel TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  sent_at TEXT,
  message TEXT
);

CREATE INDEX IF NOT EXISTS idx_clinical_trials_status ON clinical_trials(overall_status);
CREATE INDEX IF NOT EXISTS idx_clinical_trials_last_seen ON clinical_trials(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_clinical_trial_snapshots_nct ON clinical_trial_snapshots(nct_id);
CREATE INDEX IF NOT EXISTS idx_regulatory_documents_source ON regulatory_documents(source_id);
CREATE INDEX IF NOT EXISTS idx_regulatory_documents_last_seen ON regulatory_documents(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_regulatory_snapshots_document ON regulatory_document_snapshots(document_key);
CREATE INDEX IF NOT EXISTS idx_company_documents_source ON company_documents(source_id);
CREATE INDEX IF NOT EXISTS idx_company_documents_company ON company_documents(company_key);
CREATE INDEX IF NOT EXISTS idx_company_documents_last_seen ON company_documents(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_company_snapshots_document ON company_document_snapshots(document_key);
