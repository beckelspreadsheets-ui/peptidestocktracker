# Data Model

Core entities:
- peptide
- peptide_alias
- company
- security
- asset
- trial
- patent_family
- regulatory_item
- source_document
- claim
- event
- alert

Special design choice: claims are stored separately from events. A low-confidence claim can exist without becoming a high-severity alert.

## Clinical Trials

ClinicalTrials.gov records are stored in two layers:
- `clinical_trials`: current normalized state keyed by `nct_id`
- `clinical_trial_snapshots`: immutable raw JSON snapshots keyed by `nct_id` and `record_hash`

Normalized trial fields include:
- NCT ID and source URL
- brief and official titles
- overall status
- phase
- enrollment count/type
- sponsor
- primary completion date
- completion date
- last update post date
- results availability
- interventions
- conditions
- primary outcomes
- locations
- matched peptide IDs and aliases
- query terms
- source hash

Clinical trial changes create reviewable `events` rows. Event language distinguishes confirmed registry facts from inference and speculation, and includes no buy/sell recommendation.

## Regulatory Documents

FDA and Federal Register sources are stored in two layers:
- `regulatory_documents`: current normalized document state keyed by source/document key
- `regulatory_document_snapshots`: immutable content snapshots keyed by document key and content hash

Normalized regulatory fields include:
- source id and source type
- source URL
- title
- Federal Register document number, when present
- publication date, when present
- docket IDs, when present
- content hash
- extracted text
- matched peptide IDs and aliases
- route/status snippets such as injectable vs non-injectable GHK-Cu
- status terms such as `503A Bulks List`, `Category 1`, `Category 2`, `PCAC`, `included`, and `removed`
- source metadata

FDA and Federal Register changes create reviewable `events` rows. Event language must state that PCAC review, PCAC recommendations, and 503A/503B list movement are not FDA drug approval.

## Company, News, and Filing Documents

Company IR/news pages, OTC/CSE pages, and SEC filings are stored in two layers:
- `company_documents`: current normalized company-source state keyed by source/document key
- `company_document_snapshots`: immutable content snapshots keyed by document key and content hash

Normalized company-source fields include:
- source id and source type
- source URL and title
- configured company id, company name, ticker, and exchange when known
- SEC filing type, accession number, and filing date when present
- source tier and content hash
- extracted public text
- matched peptide IDs and aliases
- matched company ids
- catalyst keyword buckets such as `regulatory_or_compounding`, `commercial_launch`, `patent_or_ip`, `licensing_or_acquisition`, `clinical_asset`, `infrastructure`, and `ticker_or_listing`
- source metadata such as company tier, public/private status, liquidity risk, CIK, and primary filing document

Company-source changes create reviewable `events` rows only when peptide aliases or catalyst keyword buckets are present. SEC filing target mentions use high source confidence. Company press releases and commercial launch claims remain reviewable company-source claims, not clinical proof, FDA approval, or buy/sell recommendations. OTC/CSE/microcap events include liquidity, dilution, promotional, and regulatory risk language.

## Claim Registry

Claims are durable review records, not alerts. Each claim stores:
- claim text
- source URL and source label, when known
- source type
- claim category
- company name, when explicit
- peptide id, when explicit
- confidence
- live verification status
- target verification status from seed docs, when provided
- priority
- verification path
- evidence excerpt
- reviewer notes
- first seen and last checked timestamps
- review queue flag

External-report, AI-report, third-party-report, and trial-mirror claims are inserted with live status `needs_verification` and `needs_review=1`. Seed docs may preserve a desired `target_status`, but target status does not promote the live status.
