# Architecture

## Pipeline

1. Source adapters fetch public data.
2. Raw content is stored or hashed.
3. Alias matcher detects peptide/company/asset mentions.
4. Normalizer creates canonical source records.
5. Diff engine compares against previous snapshots.
6. Claim registry stores low-confidence claims for review.
7. Event engine creates structured events.
8. Alert scorer assigns severity/confidence/directness.
9. Digest writer and Telegram sender publish alerts.

## MVP components

- `config_loader`
- `database`
- `sources.clinicaltrials`
- `sources.fda`
- `sources.federal_register`
- `sources.pubmed`
- `sources.wipo_rss`
- `sources.sec`
- `sources.company_pages`
- `claims`
- `diffs`
- `alerts`
- `digest`
- `cli`

## Data storage

SQLite for MVP. Tables are defined in `schema/schema.sql`.
