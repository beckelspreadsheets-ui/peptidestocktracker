# Peptide Stock Tracker

Compliance-safe public-source research and alerting system for peptide regulatory, clinical, patent, commercial, and public-market catalysts.

This repo is designed to live at:

```bash
/Users/andrewferguson/peptidestocktracker
```

## What this is

A private research tracker for peptides that may become legally compoundable, prescribable, clinically validated, commercially developed, or FDA-approved in the United States.

Primary targets:
- BPC-157
- TB-500
- Thymosin beta-4 / timbetasin
- GHK-Cu / copper peptide / copper tripeptide-1

Secondary targets:
- KPV
- MOTS-c
- Semax
- Epitalon
- LL-37
- Thymosin alpha-1
- Emideltide / DSIP-related substances
- Other FDA 503A/503B peptide-review substances

## Research files Codex must read first

- `AGENTS.md`
- `PRD.md`
- `docs/RESEARCH_CONTEXT.md`
- `docs/KIMI_FINDINGS_REVIEW.md`
- `docs/GEMINI_FINDINGS_REVIEW.md`
- `docs/CLAIMS_TO_VERIFY.md`
- `docs/VERIFIED_SOURCE_MAP.md`
- `docs/COMPLIANCE.md`

## Recommended build order

1. Bootstrap Python package, config loading, SQLite schema, and tests.
2. Build claim registry and manual review queue.
3. Add ClinicalTrials.gov adapter.
4. Add FDA/Federal Register/503A adapter.
5. Add company news and filings monitors.
6. Add Telegram alerts and weekly digest.
7. Add PubMed, WIPO, USPTO/PatentsView, and patent-focused adapters.
8. Add dashboard after the data model is stable.

Website build handoff: see `docs/WEBSITE_PRD.md` for the detailed Agent OS/site-builder spec.

## Compliance reminder

This project is not financial advice and must never provide buy/sell recommendations. It should surface public-source evidence, classify confidence, and prompt follow-up research.

## Local setup

Use Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Validate the project:

```bash
pytest
```

Initialize the SQLite database:

```bash
peptide-watch init-db --db data/watch.db
```

Optional table check:

```bash
sqlite3 data/watch.db ".tables"
```

## Claim registry

Seed the manual review queue from `docs/CLAIMS_TO_VERIFY.md`:

```bash
peptide-watch claims seed --db data/watch.db --file docs/CLAIMS_TO_VERIFY.md
```

List reviewable claims:

```bash
peptide-watch claims list --db data/watch.db --review-queue
```

Add an external-report claim manually:

```bash
peptide-watch claims add \
  --db data/watch.db \
  --text "External report claim that needs primary-source verification." \
  --source-type external_report
```

Export claims:

```bash
peptide-watch claims export --db data/watch.db --format markdown
peptide-watch claims export --db data/watch.db --format csv --output data/claims.csv
```

Milestone 2 keeps external-report and AI-report claims at `needs_verification`. If a seed row has a target status such as `confirmed_primary_source`, that target is stored separately as `target_status`; the live claim status is not promoted until primary-source verification is done.

## ClinicalTrials.gov adapter

Fetch a specific official registry record:

```bash
peptide-watch clinicaltrials scan \
  --db data/watch.db \
  --no-aliases \
  --no-known-ncts \
  --nct NCT05555589
```

Scan configured known NCT IDs and peptide aliases:

```bash
peptide-watch clinicaltrials scan --db data/watch.db
```

List stored trial records:

```bash
peptide-watch clinicaltrials list --db data/watch.db --limit 20
```

The ClinicalTrials.gov adapter uses only the public API v2, stores raw snapshots and normalized trial fields, hashes records, and creates reviewable events for newly detected records and changes to status, phase, enrollment, primary completion date, last update post date, or results availability.

## FDA and Federal Register adapters

Scan configured FDA PCAC, 503A PDF, and safety-risk sources:

```bash
peptide-watch fda scan --db data/watch.db
```

Scan selected FDA sources:

```bash
peptide-watch fda scan \
  --db data/watch.db \
  --source-id fda_pcac_2026 \
  --source-id fda_503a_pdf
```

List stored FDA regulatory documents:

```bash
peptide-watch fda list --db data/watch.db --limit 20
```

Scan Federal Register FDA notices using configured PCAC queries:

```bash
peptide-watch federal-register scan --db data/watch.db
```

Run a targeted Federal Register search:

```bash
peptide-watch federal-register scan \
  --db data/watch.db \
  --query "BPC-157 KPV TB-500 MOTs-C Semax Epitalon" \
  --per-page 5
```

The regulatory adapters store current normalized documents and immutable snapshots, hash source content, match peptide aliases, preserve route/status snippets such as injectable vs non-injectable GHK-Cu, and create reviewable events when official content changes. PCAC review and 503A list movement are not FDA drug approval.

## Company/news/filing monitors

Scan configured public company IR, news, CSE, and OTC page sources:

```bash
peptide-watch company-pages scan --db data/watch.db
```

Scan a selected company/news source:

```bash
peptide-watch company-pages scan \
  --db data/watch.db \
  --source-id hims_ir_news
```

List stored company page records:

```bash
peptide-watch company-pages list --db data/watch.db --limit 20
```

Scan recent public SEC EDGAR filings for configured U.S. public companies:

```bash
export PEPTIDE_WATCH_SEC_USER_AGENT="peptide-watch/0.1 your-email@example.com"
peptide-watch sec scan --db data/watch.db --max-filings 3
```

Scan selected SEC companies or forms:

```bash
peptide-watch sec scan \
  --db data/watch.db \
  --company-id hims \
  --form 10-K \
  --form 10-Q \
  --max-filings 2
```

List stored SEC filing records:

```bash
peptide-watch sec list --db data/watch.db --limit 20
```

The company/news/filing monitors store normalized `company_documents` and immutable snapshots. Events are created only when a public page or filing contains peptide aliases or catalyst keywords such as compounding, 503A, product launch, patents, licensing, acquisition, clinical-trial language, or peptide infrastructure. Company press releases and commercial claims remain reviewable company-source claims, not clinical proof, FDA approval, or trading recommendations. OTC/CSE/microcap events include liquidity, dilution, promotional, and regulatory risk language.

Do not add buy/sell recommendations, price targets, private data, or non-public sources.
