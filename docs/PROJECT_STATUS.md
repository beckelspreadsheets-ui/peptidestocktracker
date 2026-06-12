# Peptide Watch — Project Status & Handoff

**Last updated:** 2026-06-12
**Branch:** `master` (21 commits, ~13 ahead of `origin` — NOT yet pushed)
**Tests:** 120 passing · ruff clean · language gate clean · integrity 0 corrupted

This is the single catch-up doc. For design depth see
`docs/PEPTIDE_WATCH_HARDENING_ROADMAP.md`; for alert tiering see
`docs/ALERT_TAXONOMY.md`; for running it see `docs/OPERATIONS.md`.

---

## What this is

A compliance-safe, public-source catalyst tracker for a peptide watchlist (BPC-157,
TB-500, thymosin beta-4 / RGN-259, GHK-Cu, MOTS-c, LL-37, etc.) and the public/microcap
companies exposed to them. It is a **local CLI + SQLite** tool (`data/watch.db`) — no web
server, no login, no domain. Alerts leave via console/file/webhook channels. The product
rule (no recommendations/advice; public sources only) is enforced by a CI language gate.

Goal: **catch early movers** in the peptide-compounding regulatory wave — surface ~10
candidates to find 1 gem — and stay ahead of the curve by weighting *leading* signals.

---

## Hardening done (PR1–PR15, all merged to master)

- **PR1** config validation + secret-rejection, `uv` lockfile, SQLite WAL/pragmas, `backup-db`
- **PR2** run ledger (tracked runs, per-source task state), failure isolation, auto-resume,
  circuit breaker, lockfile, JSON logging, run summaries, migrations runner
- **PR3/4** shared `HttpClient` (retry+backoff honoring Retry-After, timeouts, per-host
  throttle, conditional GETs, **urllib fallback for TLS-fingerprint-blocked hosts**),
  scanner registry, conditional-GET cursors
- **PR5** two-hash change detection (raw vs canonical), event identity key (idempotent),
  disappearance hysteresis, parser-version suppression, **per-source single-transaction
  atomicity + per-entry isolation**
- **PR6** transactional outbox (`deliveries`), severity tiers, batched delivery, digest,
  console/file/**webhook** channels
- **PR7** content-addressed raw blobs, `replay` (zero-network re-derivation), `verify`
  (integrity), snapshot immutability triggers
- **PR8** CI language gate (`tools/check_language.py`)
- **PR9** coverage map enforced (`config check` fails on unclaimed sources), `watched_pages`
  catch-all, **SEC full-text discovery**
- **PR10** live-probed source audit, FDA 503B PDF, broader queries
- **PR11** openFDA enforcement (recalls), webhook channel, ops scripts, live-run bug fixes
  (SEC ticker URL, openFDA OR-syntax, ClinicalTrials 403 fallback)
- **PR12** USPTO patents (key-gated), assignee→public-company = critical
- **PR13** NIH RePORTER grants, GlobeNewswire newswire feeds
- **PR14** Regulations.gov (leading regulatory signal — docket/comment-period detection)
- **PR15** openFDA drug shortages (compounding-demand signal), FDA 503B facilities page
- **Post-PR15 tuning:** retiered the funnel (immediate = early movers only; routine
  watchlist mentions + existing-trial backfill → digest; fund filings dropped),
  `new_company_peptide_disclosure` discovery event, `discoveries` CLI, precision-tuned
  full-text phrases (dropped noisy LL-37/TB-500/CB4211 codes)

## The 12 scanner families (all live-verified)

`clinicaltrials` · `fda` (pages/PDFs incl. 503A, 503B, PCAC, safety, import alert) ·
`federal_register` · `sec_edgar` (watchlist filings) · `sec_fulltext` (all-filer
discovery) · `pubmed` · `nih_reporter` · `regulations_gov` · `openfda_enforcement` ·
`openfda_shortages` · `watched_pages` (catch-all page/RSS incl. GlobeNewswire) ·
`uspto_patents` (key-gated, only registers when key present).

## Signal ladder (earliest → latest)

regulations.gov dockets → NIH/SBIR grants → USPTO patents → PubMed → ClinicalTrials →
SEC full-text discovery → Federal Register / FDA pages → openFDA recalls / newswires.
Plus demand (`openfda_shortages`) and supply (`fda_503b_facilities`) flanks.

---

## Current operational state

- A **launchd agent** `com.peptidewatch.daily` is installed on this Mac mini, firing the
  scan→deliver→digest pipeline every 4h. Plist:
  `~/Library/LaunchAgents/com.peptidewatch.daily.plist`. Uses the file channel.
  Stop with: `launchctl unload ~/Library/LaunchAgents/com.peptidewatch.daily.plist`.
- Last full run: 12/12 families done, ~1,100 fetched, 0 failures.
- The DB has historical events from the old (pre-retier) tiering already delivered; new
  runs use the new tiering automatically.

## Keys / secrets (env vars only — never in config)

| Var | Status | Purpose |
|---|---|---|
| `PEPTIDE_WATCH_USPTO_API_KEY` | **set in user's interactive shell** (Keychain) | enables `uspto_patents`; not in launchd env yet |
| `PEPTIDE_WATCH_REGULATIONS_API_KEY` | NOT set (uses public DEMO_KEY, rate-limited) | get free key at api.data.gov for headroom |
| `PEPTIDE_WATCH_WEBHOOK_URL` | NOT set | Discord/Slack webhook for phone alerts |
| `PEPTIDE_WATCH_SEC_USER_AGENT` | optional | SEC asks for a contact string |

---

## TODO — what's left

**Operational (user):**
1. Get a free **api.data.gov key** for Regulations.gov → set `PEPTIDE_WATCH_REGULATIONS_API_KEY`
   (DEMO_KEY threw 429 under normal scanning).
2. To run **USPTO under the scheduler**, put its key in the launchd plist `EnvironmentVariables`
   (or the VPS crontab) — currently only runs from the user's shell.
3. **Push to origin** (not yet done) so the VPS is a `git clone`.
4. **Stand up the VPS** (any 1-vCPU box): clone, `uv sync --locked`, install `uv`, add the
   two crontab lines from `docs/OPERATIONS.md`, set keys in the crontab header. No domain needed.

**Soak-week tuning (review the data, then decide):**
5. Run `peptide-watch discoveries` daily; promote real new filers (e.g. BioScience Health
   Innovations/BHIC, Regenerative Medical Technology/RMTG, Carnyx) to `config/companies.yaml`
   — this graduates them from full-text discovery to full per-company monitoring. **This is
   the core profit loop.**
6. Watch for remaining full-text false positives; tighten the `sec_fulltext` phrase group
   further if needed.
7. Link watchlist-adjacent discoveries the name-matcher missed (e.g. CohBar/CWBR ≈ existing
   `tuhura_cohbar_legacy`).
8. After a week, review immediate-tier volume and `SELECT event_type, COUNT(*) ... GROUP BY`
   to confirm tiering feels right; adjust severities in the source `_severity` functions.

**Future sources (drop-in, by earliness — all probed or noted):**
9. **SBIR.gov** all-agency awards (DoD/DARPA peptide $) — public API was returning
   TooManyRequests/Forbidden from every IP; retry when it recovers.
10. EPO OPS / PatentsView (key-gated patents); EU CTR / WHO ICTRP (ex-US trials);
    per-company PRNewswire/Business Wire feeds.

---

## Key commands

```bash
uv run peptide-watch config check        # validate config + source coverage (CI gate)
uv run peptide-watch scan                # one tracked run, all families, failure-isolated
uv run peptide-watch runs list           # ledger: every run's status
uv run peptide-watch runs show <run_id>  # per-source counts and errors
uv run peptide-watch deliver --channel console|file|webhook   # immediate (critical/high)
uv run peptide-watch digest --dry-run    # medium/low summary (the review pile)
uv run peptide-watch discoveries         # gem queue: new filers, funds filtered, freshest first
uv run peptide-watch verify              # re-hash blobs/snapshots for corruption
uv run peptide-watch backup-db           # dated VACUUM INTO backup
uv run peptide-watch list-adapters       # registered scanner families
uv run peptide-watch uspto-check         # verify USPTO key + print response shape
```

Pipeline scripts: `scripts/peptide_watch_daily.sh` (scan→deliver→digest),
`scripts/peptide_watch_weekly.sh` (verify+backup). Both launchd/cron-safe.
