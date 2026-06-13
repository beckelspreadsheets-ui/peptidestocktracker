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

## HQ operating-system layer

The deployed Peptide Watch HQ has two durable stores:

- **Fact store:** the tracker SQLite database with public-source records, raw
  blobs/snapshots, runs, events, deliveries, and deterministic source facts.
- **Operator memory:** a separate SQLite database for workflow state such as
  watched, promoted, ignored, and archived entities, factual attention counts,
  notes, and briefing cursors.

The operator store can change dashboard ordering and briefing labels, but it
must not change source facts or create recommendations. Read-only cockpit users
can inspect source facts and operator state exposed by safe API endpoints.
Mutations remain in the Telegram HQ command surface until dashboard auth is
explicitly designed and tested.

For reusable verticals and template boundaries, see `docs/PRODUCTIZATION.md`.
