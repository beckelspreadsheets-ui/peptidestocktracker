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
  claim_text TEXT NOT NULL,
  entity_name TEXT,
  peptide_id TEXT,
  source_label TEXT,
  source_url TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  confidence TEXT NOT NULL DEFAULT 'low',
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
