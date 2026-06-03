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
6. Add PubMed, WIPO, USPTO/PatentsView, and SEC adapters.
7. Add Telegram alerts and weekly digest.
8. Add dashboard after the data model is stable.

## Compliance reminder

This project is not financial advice and must never provide buy/sell recommendations. It should surface public-source evidence, classify confidence, and prompt follow-up research.
