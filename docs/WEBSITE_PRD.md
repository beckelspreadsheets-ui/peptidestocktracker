# PRD - Peptide Stock Tracker Website

Goal: Build a private, interactive website for Peptide Stock Tracker that turns the local repo's public-source monitoring data into a clear research dashboard, watchlist, event feed, source-health console, and manual review workspace.

Success means:
- The website reads the current local repo data from SQLite/config files and presents the watchlist, events, claims, regulatory documents, clinical trials, company documents, and source status in one cohesive interface.
- Every screen preserves the compliance posture: public-source evidence, confidence labels, review status, source URLs, and clear "not a buy/sell recommendation" language.
- The website supports a daily research workflow: see what moved, see what changed, open the evidence, classify the item, and decide the next research step.
- The website is ready to extend into patent, PubMed, quote, and alerting modules without redesigning the information architecture.

Stop when: A local developer can run the app against the repo, open the dashboard, inspect all existing stored data, review claims/events, and understand the next data modules required for full robustness.

## 1. Product Context

Peptide Stock Tracker is a compliance-safe public-source biotech catalyst monitor focused on peptide-related regulatory, clinical, patent, commercial, and public-market signals.

The existing repo already includes:
- Python 3.12 package under `src/peptide_watch`
- Typer CLI
- SQLite schema in `schema/schema.sql`
- YAML configs in `config/`
- Claim registry
- ClinicalTrials.gov adapter
- FDA/Federal Register adapters
- Company page monitor
- SEC EDGAR monitor
- Tests for config, DB init, claims, clinical trials, regulatory documents, and company monitors
- Shareable watchlist at `docs/WATCHLIST.md`

The website should turn this backend into a private research cockpit. The website should emphasize evidence review, source provenance, and workflow clarity over marketing or promotional presentation.

## 2. Primary Users

### Research Operator

The research operator checks the dashboard daily, reviews new events, verifies claims, and prioritizes follow-up research.

Needs:
- Fast view of latest events and source changes
- Watchlist with current public stocks and private/non-stock entities
- Evidence links and excerpts
- Status labels for verification, confidence, severity, directness, and source tier
- Clear distinction between fact, inference, speculation, and market context

### Future Builder / Maintainer

The maintainer extends adapters, adds market data, adds patent data, and improves alerting.

Needs:
- Source-health visibility
- Job history and failure reasons
- Config-driven watchlist
- API and schema boundaries that match the Python repo
- Tests and deterministic local data behavior

## 3. Compliance Requirements

Every event, claim, alert, card, and detail page must display enough context to preserve the project's compliance posture.

Required compliance fields:
- Source URL
- Source type
- Evidence tier or confidence
- Verification status
- Fact / inference / speculation framing
- Possible market relevance as context only
- Review status

Required global disclaimer:

```text
This is public-source research, not financial advice. This is not a buy/sell recommendation. Verify independently.
```

Required microcap/OTC/CSE language:

```text
OTC/CSE/microcap names may carry liquidity, dilution, promotional, and regulatory risk.
```

Required regulatory language:

```text
PCAC review, PCAC recommendations, and 503A/503B list movement are not FDA drug approval.
```

Required company-source language:

```text
Company press releases and commercial claims are company-source claims, not independently verified clinical evidence.
```

Use these statements in context on dashboard footers, event detail pages, company detail pages, and claim review views.

## 4. Current Watchlist Data

Read primary watchlist data from `config/companies.yaml` and present it in the website.

Public-stock watchlist:
- RegeneRx Biopharmaceuticals - `RGRX` / OTC - Tier 1
- HLB Therapeutics - `115450` / KOSDAQ - Tier 1
- PharmaTher Holdings - `PHRRF` / OTCQB and `PHRM` / CSE - Tier 2
- The Precision Peptide Company - `PNGAF` / OTCQB and `BPC` / CSE per current config - Tier 2
- Hims & Hers Health - `HIMS` / NYSE - Tier 2
- LifeMD - `LFMD` / NASDAQ - Tier 2
- Harrow - `HROW` / NASDAQ - Tier 2
- TuHURA / CohBar legacy / Morphogenesis CVR - `HURA` / NASDAQ and private CVR - Tier 2
- Bachem Holding AG - `BANB` / SIX - Tier 2
- PolyPeptide Group - `PPGN` / SIX - Tier 2
- MMA.INC - `MMA` / NYSE American - Tier 3
- PMD / Promore / Pergasus AB - `PMDS` / Stockholm - Tier 3

Private/non-stock watch items:
- ReGenTree LLC
- Hudson Biotech
- Diagen d.o.o.
- NEOVA / Pharma Cosmetics / Skin Biology / ProCyte legacy
- Context-only telehealth/longevity platforms when sourced publicly

## 5. Information Architecture

Build the website around these main sections:

1. Dashboard
2. Watchlist
3. Events
4. Claims Review
5. Companies
6. Peptides
7. Regulatory
8. Clinical Trials
9. Company Documents and SEC Filings
10. Source Health
11. Alerts and Digest
12. Settings / Config

Use a left navigation rail or top-level app navigation that keeps these sections one click away.

## 6. Page Requirements

### 6.1 Dashboard

Purpose: Show the daily operating picture.

Required dashboard modules:
- Latest reviewable events
- Critical/high severity events
- Watchlist companies with recent changes
- Regulatory catalyst countdowns
- Claims needing review
- Source health summary
- Recent clinical trial changes
- Recent FDA/Federal Register changes
- Recent company page/SEC filing changes
- Market context panel once quote snapshots exist

Required dashboard filters:
- Severity
- Confidence
- Source type
- Peptide
- Company
- Needs review
- Date range

Required dashboard behavior:
- Sort latest events first.
- Highlight new/unreviewed records.
- Show source URL on every event row.
- Display compliance disclaimer in a persistent footer or sidebar.
- Link each dashboard card to the relevant detail view.

### 6.2 Watchlist

Purpose: Show the current public and private entity universe in a shareable, sortable view.

Required columns:
- Tier
- Company/entity
- Ticker
- Exchange
- Public/private status
- Peptide links
- Relationship/rationale
- Confidence
- Liquidity risk
- Latest event date
- Open review items count
- Source coverage status

Required filters:
- Tier
- Peptide
- Public/private
- Exchange
- Liquidity risk
- Confidence
- Has recent events
- Has open review items

Required interactions:
- Click company/entity to open a detail page.
- Export filtered watchlist to Markdown or CSV.
- Display data source as `config/companies.yaml`.
- Display a timestamp for generated/exported watchlist files.

### 6.3 Company Detail

Purpose: Give a complete research view for one company/entity.

Required header fields:
- Company name
- Ticker and exchange
- Tier
- Public/private status
- Relationship/rationale
- Peptide links
- Confidence
- Liquidity risk
- Last scanned date
- Latest event date

Required tabs:
- Overview
- Events
- Claims
- SEC filings
- Company pages/news
- Clinical trials
- Regulatory links
- Patents, when available
- Market context, when quote data exists
- Source history

Required overview content:
- Watchlist rationale from config
- Latest reviewable events
- Open claims needing review
- Source coverage checklist
- Compliance notes specific to the entity

Required event content:
- Event type
- Severity
- Confidence
- Directness
- What changed
- Why it matters
- Possible market relevance
- Source URL
- Created timestamp
- Needs-review status

### 6.4 Peptide Detail

Purpose: Show all signals tied to a target peptide.

Required peptide fields:
- Peptide ID
- Display name
- Primary/secondary target
- Aliases
- Related companies
- Related trials
- Related regulatory documents
- Related company documents
- Related claims
- Latest events

Required behavior:
- Keep TB-500 fragment separate from full-length thymosin beta-4/timbetasin.
- Preserve GHK-Cu route-specific context when regulatory documents mention injectable or non-injectable forms.
- Show aliases from `config/peptides.yaml`.

### 6.5 Events

Purpose: Give a full review queue for detected changes.

Required columns:
- Event ID
- Created date
- Event type
- Severity
- Confidence
- Directness
- Peptide
- Company
- Source type
- Title
- Needs review

Required detail view:
- Title
- What changed
- Why it matters
- Confidence
- Severity
- Directness
- Stock market relevance
- Source URL
- Source document metadata
- Related company and peptide
- Review actions

Required review actions:
- Mark as reviewed
- Add reviewer note
- Link to existing claim
- Create new claim
- Flag for follow-up
- Export event as Markdown

### 6.6 Claims Review

Purpose: Let the user review, verify, downgrade, or exclude claims.

Required columns:
- Claim ID
- Status
- Target status
- Priority
- Company
- Peptide
- Category
- Source type
- Source label
- First seen date
- Last checked date
- Needs review

Required status actions:
- `needs_verification`
- `confirmed_primary_source`
- `confirmed_secondary_source`
- `contradicted`
- `stale`
- `excluded`

Required claim detail fields:
- Claim text
- Evidence excerpt
- Source URL
- Verification path
- Reviewer notes
- Imported-from metadata
- Related events

Required behavior:
- Keep external-report and AI-report claims at `needs_verification` until a reviewer promotes them.
- Preserve target status separately from live status.
- Show source type prominently.

### 6.7 Regulatory

Purpose: Show FDA and Federal Register regulatory monitoring.

Required sections:
- FDA PCAC pages
- FDA 503A/503B list sources
- FDA safety-risk page
- Federal Register notices
- Route/status snippets
- Matched peptides

Required fields:
- Source ID
- Source type
- Title
- URL
- Publication date
- Document number
- Docket IDs
- Status terms
- Route notes
- Content hash
- First seen
- Last seen
- Updated at

Required behavior:
- Display the regulatory disclaimer on every detail view.
- Highlight July 23-24, 2026 PCAC as a key upcoming catalyst.
- Preserve GHK-Cu route distinction.

### 6.8 Clinical Trials

Purpose: Show normalized ClinicalTrials.gov records and changes.

Required columns:
- NCT ID
- Status
- Phase
- Sponsor
- Enrollment
- Primary completion date
- Results availability
- Peptide matches
- Last update post date
- Source URL

Required detail fields:
- Brief title
- Official title
- Conditions
- Interventions
- Primary outcomes
- Locations
- Raw registry snapshot link or JSON view
- Change events

Required behavior:
- Treat official registry records as source facts.
- Present trial changes as research signals, not clinical proof or investment merit.

### 6.9 Company Documents and SEC Filings

Purpose: Show company-source and filing-source documents detected by milestone 5 adapters.

Required columns:
- Source ID
- Source type
- Company
- Ticker
- Exchange
- Filing type
- Filing date
- Accession number
- Keyword matches
- Peptide matches
- First seen
- Last seen
- URL

Required detail fields:
- Extracted public text
- Keyword match buckets
- Matched aliases
- Company matches
- Metadata JSON
- Content hash
- Snapshot history

Required behavior:
- Label SEC filings as high-confidence public filing sources.
- Label company pages and press releases as company-source claims.
- Include microcap risk language for OTC/CSE names.

### 6.10 Source Health

Purpose: Make robustness visible.

Required source-health data, even if initially empty or stubbed:
- Source ID
- Source type
- URL
- Tier
- Cadence
- Last run time
- Last success time
- Last error time
- Last error message
- HTTP status
- Current content hash
- Previous content hash
- Consecutive failures
- Average runtime
- Next scheduled run

Required job-run view:
- Job ID
- Adapter name
- Started at
- Finished at
- Status
- Fetched count
- Inserted count
- Changed count
- Events created
- Error message
- Logs excerpt

Implementation note: The current schema does not yet include `job_runs` or `source_health`. Add these tables before the website treats source health as live data.

### 6.11 Alerts and Weekly Digest

Purpose: Prepare the interface for milestone 6.

Required alert views:
- Pending alerts
- Sent alerts
- Suppressed alerts
- Weekly digest preview
- Telegram delivery status, when configured

Required digest sections:
- Critical/high events
- Regulatory updates
- Clinical trial updates
- Company/SEC updates
- Claims needing review
- Source failures
- Watchlist market context, when quote data exists

Required behavior:
- Generate digest text from stored events and claims.
- Include source links and compliance language.
- Keep alerts reviewable before sending in MVP.

### 6.12 Settings / Config

Purpose: Show the loaded repo config and environment status.

Required config views:
- Peptides
- Companies
- Sources
- Queries
- Alert rules

Required environment checks:
- Python package import status
- SQLite DB path
- Schema version or table presence
- Required environment variables
- Optional provider keys present/missing without displaying secret values

## 7. Market Data Requirements

The current repo does not yet include durable market quote storage. Add market data as a separate context layer.

Required future tables:
- `market_quote_snapshots`
- `market_symbols`
- `market_provider_runs`

Required quote snapshot fields:
- Symbol
- Exchange
- Provider
- Quote timestamp
- Open
- High
- Low
- Close or last price
- Previous close
- Change percent
- Volume
- Dollar volume when calculable
- Delayed/realtime flag
- Currency
- Raw payload hash

Required market-context behavior:
- Show price moves as context, not evidence.
- Link market moves to events only when a public-source catalyst exists.
- Flag abnormal moves using transparent thresholds such as daily percent move, volume multiple, and dollar volume.
- Display provider name and timestamp on every quote.
- Store API keys in environment variables.

Suggested quote-provider abstraction:
- Create one provider interface.
- Add provider-specific adapters behind that interface.
- Store provider terms/limits in config.
- Use delayed data labels when data is delayed.

## 8. Patent and New-Company Discovery Requirements

The website should reserve UI and API space for patent and discovery modules even if the first build displays empty states.

Required future patent fields:
- Patent publication number
- Application number
- Grant number
- Assignee
- Inventors
- Filing date
- Publication date
- Grant date
- Jurisdiction
- Title
- Abstract
- Claims excerpt
- Matched peptide aliases
- Matched companies
- Legal status
- Assignment status
- Source URL

Required discovery behavior:
- Detect new assignees mentioning target peptides.
- Create candidate company records for review.
- Keep new companies in a candidate state until manually promoted to watchlist.
- Preserve external claims as `needs_verification`.

## 9. Backend Requirements

Preferred backend shape:
- Use FastAPI for the local API layer.
- Read from the existing SQLite database at `data/watch.db`.
- Reuse repo config loaders from `src/peptide_watch/config.py`.
- Reuse existing normalization/data modules where practical.
- Keep CLI and website data paths compatible.

Required API endpoints:
- `GET /api/health`
- `GET /api/config/peptides`
- `GET /api/config/companies`
- `GET /api/config/sources`
- `GET /api/watchlist`
- `GET /api/events`
- `GET /api/events/{id}`
- `POST /api/events/{id}/review`
- `GET /api/claims`
- `GET /api/claims/{id}`
- `POST /api/claims/{id}/status`
- `GET /api/clinical-trials`
- `GET /api/clinical-trials/{nct_id}`
- `GET /api/regulatory-documents`
- `GET /api/regulatory-documents/{document_key}`
- `GET /api/company-documents`
- `GET /api/company-documents/{document_key}`
- `GET /api/source-health`
- `GET /api/job-runs`
- `GET /api/alerts`
- `GET /api/digest/weekly/preview`

Required API behavior:
- Return JSON with stable field names.
- Support pagination.
- Support filtering by peptide, company, severity, confidence, source type, date range, and review status.
- Return source URLs and evidence text with every event/detail response.
- Return empty arrays for unavailable future modules instead of failing.

## 10. Frontend Requirements

Preferred frontend shape:
- Use a modern React or Next.js app if the website builder supports it.
- Use a dense operational dashboard layout.
- Use tables, tabs, filters, badges, side panels, and detail drawers.
- Use responsive layouts for desktop and tablet first.

Visual direction:
- Build a quiet, research-focused interface.
- Use compact cards only for summary modules.
- Use tables for watchlist, events, claims, trials, filings, and source health.
- Use badges for severity, confidence, directness, source tier, verification status, and needs-review status.
- Use clear source-link buttons on every evidence row.
- Use restrained color coding:
  - Critical: red
  - High: orange
  - Medium: amber/blue
  - Low: gray
  - Confirmed: green
  - Needs verification/review: amber
  - Contradicted/excluded: gray/red

Required navigation:
- Persistent app navigation
- Global search across companies, peptides, tickers, NCT IDs, document keys, claims, and events
- Breadcrumbs on detail pages
- Deep links for every event, claim, company, peptide, trial, and document

Required empty states:
- Explain what data source needs to run.
- Show the exact CLI command when helpful.
- Link to relevant config/docs.

## 11. Daily Research Workflow

The website must support this daily flow:

1. Open Dashboard.
2. Review critical/high events.
3. Check source health for failures.
4. Open Watchlist and sort by latest event.
5. Open any company with a new event or abnormal market context.
6. Open the source document and evidence excerpt.
7. Mark event reviewed or create a follow-up claim.
8. Update claim status only after source verification.
9. Preview weekly digest.

## 12. Robustness Requirements

Add these robustness features before relying on the website as a daily production tracker:

### 12.1 Job Runs

Create `job_runs` with:
- ID
- Adapter name
- Source IDs
- Started at
- Finished at
- Status
- Fetched count
- Stored count
- Inserted count
- Changed count
- Events created
- Error message
- Metadata JSON

### 12.2 Source Health

Create `source_health` with:
- Source ID
- Last success at
- Last failure at
- Last error message
- Consecutive failures
- Last content hash
- Last HTTP status
- Last runtime ms
- Updated at

### 12.3 Review Actions

Add durable review fields or tables for:
- Event reviewed status
- Reviewer notes
- Reviewed at
- Reviewed by
- Follow-up status

### 12.4 Market Context

Add quote snapshots and quote-provider runs before displaying market movers.

### 12.5 Scheduling

Add a scheduler or documented cron entry for:
- ClinicalTrials.gov scans
- FDA scans
- Federal Register scans
- Company page scans
- SEC scans
- Market quote snapshots
- Weekly digest generation

## 13. Data Mapping From Current Repo

Use these current files as source-of-truth inputs:
- `config/peptides.yaml` -> peptide universe and aliases
- `config/companies.yaml` -> watchlist companies/entities
- `config/sources.yaml` -> source catalog
- `config/queries.yaml` -> query groups
- `config/alert_rules.yaml` -> severity/confidence/review defaults
- `schema/schema.sql` -> database schema
- `docs/WATCHLIST.md` -> shareable current watchlist language
- `docs/COMPLIANCE.md` -> compliance copy
- `docs/SOURCE_ADAPTERS.md` -> adapter expectations
- `docs/DATA_MODEL.md` -> storage semantics

Use these current SQLite tables:
- `claims`
- `events`
- `alerts`
- `source_documents`
- `clinical_trials`
- `clinical_trial_snapshots`
- `regulatory_documents`
- `regulatory_document_snapshots`
- `company_documents`
- `company_document_snapshots`

## 14. MVP Acceptance Criteria

The first website build is complete when:
- The app starts locally from the repo.
- The app connects to `data/watch.db`.
- The app displays the watchlist from config.
- The app displays events from SQLite.
- The app displays claims and supports status updates.
- The app displays clinical trial records.
- The app displays regulatory documents.
- The app displays company documents and SEC filings.
- The app displays source-health placeholders with clear next steps if source-health tables are not present.
- The app includes compliance language on dashboard, detail pages, and exports.
- The app provides Markdown/CSV export for watchlist and selected event/claim views.
- The app passes frontend tests and any backend API tests added by the builder.

## 15. Follow-On Milestones

### Website Milestone A - Read-Only Dashboard

Build the API and frontend views for watchlist, events, claims, trials, regulatory documents, and company documents.

### Website Milestone B - Review Workflow

Add claim status updates, event review actions, reviewer notes, and follow-up flags.

### Website Milestone C - Robust Operations

Add `job_runs`, `source_health`, scheduler visibility, source failure banners, and adapter run controls.

### Website Milestone D - Market Context

Add quote snapshots, market mover panels, abnormal move flags, and catalyst-linking workflow.

### Website Milestone E - Patent and Discovery

Add patent records, assignee matching, candidate-company review, and patent timeline views.

### Website Milestone F - Alerts and Digest

Add Telegram alert review, weekly digest preview, send logs, and alert suppression.

## 16. Builder Notes For Agent OS

Read the repo before building:
- Start with `README.md`, `PRD.md`, `docs/COMPLIANCE.md`, `docs/DATA_MODEL.md`, `docs/SOURCE_ADAPTERS.md`, and this file.
- Inspect `schema/schema.sql` and `src/peptide_watch/cli.py`.
- Use existing config loaders and SQLite schema where practical.
- Add new tables through `schema/schema.sql` and `src/peptide_watch/database.py` migrations.
- Add tests for every backend endpoint and every critical UI flow.
- Keep public-source provenance visible throughout the app.

Deliverables:
- Website source code in an agreed app directory.
- Local run instructions in `README.md`.
- API route documentation.
- Tests.
- Screenshots or visual QA notes for dashboard, watchlist, company detail, events, and claims review.
- Summary of added tables, endpoints, and UI views.
