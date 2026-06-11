# Peptide Watch — Engineering Hardening Roadmap

**Status:** Draft v4 — first slice complete (PR1, PR2, PR5 + atomicity fix) reconciled and implemented
**Last updated:** 2026-06-11
**Scope:** Reliability, correctness, and maintainability of the `peptide-watch` data pipeline
**Out of scope:** Domain/watchlist content, research methodology

---

## Purpose and how to use this report

This is an implementation reference for hardening `peptide-watch` from a working prototype
into a robust, unattended, long-running monitoring system. It is written entirely in
software-engineering terms and deliberately contains no domain detail, so it can be handed to
any model — including Fable 5 — without tripping content classifiers.

Work it one **workstream** at a time. Each workstream has a goal, a design, schema where
relevant, and explicit **acceptance criteria** you can turn into tests. Track progress in the
checklist at the bottom. The "Working with Fable and Claude Code" section explains the
recommended split between design review (Fable) and implementation against the live repo
(Opus/Sonnet in Claude Code).

---

## Caveats this report carries forward

This roadmap was originally designed from a written description of the system, **not** from
the actual source. Before implementing any workstream:

1. Diff each proposed module/table against what already exists in `src/peptide_watch/`,
   `schema/`, and `config/`. Some of this may already be present under different names.
2. Treat proposed names (tables, modules, CLI commands) as suggestions, not fixed contracts.
3. Reconcile the proposed schema against the current `schema.sql` before writing migrations.

---

## Priority and dependency graph

```
P0a  Run ledger + failure isolation ──┐
P0b  Config validation + pinning      │
                                      ▼
P1   Adapter protocol + shared HTTP layer
                                      │
        ┌─────────────────────────────┤
        ▼                             ▼
P2   Canonicalization +          P3  Outbox alert
     event identity                  pipeline
        │                             │
        ▼                             ▼
P4   Replay / backfill           P5  Digest / severity tiers
P6   Migrations runner ── can run in parallel from P0
P7   Snapshot immutability enforcement
P8   CI language gate ── independent, do anytime
```

`P0a`/`P0b` and `P1` are load-bearing; everything else composes on top. `P6` (migrations) and
`P8` (CI gate) are independent and cheap — schedule them opportunistically.

---

## Recommended first slice

This is enterprise-grade hardening for a solo-operated tool, so do not build all of it before
shipping. The highest-leverage subset that removes silent failures and false alerts:

- **P0b — Config validation + pinning** (cheap, prevents silently broken sources)
- **P0a — Run ledger + failure isolation + logging** (the spine; gives crash recovery)
- **P2 — Two-hash change detection + event identity + hysteresis** (correctness of alerts)

Build those three, run the tool unattended for a week, then decide whether the adapter
protocol, outbox, and replay layers are worth adding.

---

## P0a — Run ledger, failure isolation, crash recovery

**Goal:** Every scan is a tracked run with per-source task state, so a crash or a single bad
source never corrupts state or silently kills the pipeline.

**New module:** `src/peptide_watch/runtime/ledger.py`

**Tables (via migration):**

```sql
CREATE TABLE runs (
  run_id       TEXT PRIMARY KEY,        -- uuid7, sortable
  started_at   TEXT NOT NULL,
  finished_at  TEXT,
  status       TEXT NOT NULL CHECK (status IN ('running','completed','interrupted','failed')),
  summary_json TEXT                     -- per-run rollup, written at close
);

CREATE TABLE run_tasks (
  run_id     TEXT NOT NULL REFERENCES runs(run_id),
  source_id  TEXT NOT NULL,
  status     TEXT NOT NULL CHECK (status IN ('pending','running','done','error','skipped')),
  attempt    INTEGER NOT NULL DEFAULT 0,
  error      TEXT,
  started_at TEXT,
  finished_at TEXT,
  PRIMARY KEY (run_id, source_id)
);

CREATE TABLE source_cursors (
  source_id     TEXT PRIMARY KEY,
  etag          TEXT,
  last_modified TEXT,
  cursor_json   TEXT,                    -- adapter-defined opaque cursor
  updated_at    TEXT NOT NULL
);
```

**Design:**

- A scan creates one `runs` row and one `run_tasks` row per enabled source (all `pending`).
- Each source runs inside its own `try/except`; an adapter exception marks that task `error`
  with the traceback and the loop continues. Nothing aborts the run except
  `KeyboardInterrupt`/`SystemExit`.
- Each source's writes (snapshot insert + record upsert + event insert) commit in **one**
  SQLite transaction, so a crash mid-source leaves no partial state.
- On startup, any `runs` row stuck `running` is marked `interrupted`; resume re-executes only
  `pending`/`error` tasks under a new `attempt` value.
- Overlap prevention: `flock` on a lockfile (`peptide_watch.lock`) next to the DB.
- **Scheduling stays external** (launchd timer / cron) — a fresh process per run plus the
  ledger gives crash recovery for free; an in-process scheduler is a liability for an
  unattended tool.
- Circuit breaker: track consecutive failures per source; after N (default 3) consecutive
  failed runs, mark the source `skipped` with an exponential cool-down and surface it in the
  run summary so it is never silently dead.
- Structured logging (stdlib `logging` with a JSON formatter — fewer deps than `structlog`);
  bind `run_id` and `source_id` into every line.
- Run summary (sources scanned / changed / events / errors / durations) is computed from
  `run_tasks` + event counts, stored in `runs.summary_json`, printed as the CLI epilogue, and
  reused verbatim as the digest header.
- SQLite hygiene in the same change: `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`,
  `busy_timeout`, and a nightly `VACUUM INTO backups/peptide_watch-YYYYMMDD.db`.

**New CLI:** `scan`, `scan --resume`, `runs list`, `runs show <id>`.

**Acceptance criteria:**
- Killing the process mid-scan and re-running with `--resume` completes only the unfinished
  sources and produces no duplicate records or events.
- A source that raises does not prevent other sources from completing; its failure appears in
  the run summary.
- After 3 consecutive failed runs a source is auto-skipped and reported.

---

## P0b — Config validation, secrets, dependency pinning

**Goal:** Config errors fail loudly at load time; secrets never live in config files;
dependencies are reproducible.

**New module:** `src/peptide_watch/settings.py` using `pydantic-settings`.

**Design:**
- Typed models for app settings and for each source entry (id, adapter name, URL, schedule,
  rate limit, tracked fields, watchlist refs). `extra="forbid"` so a config typo is a hard
  error instead of a silently disabled source.
- Secrets (alert tokens, chat ids) come only from env vars / `.env`; config references them by
  name, never value. Validation rejects token-shaped strings found inside config files.
- New CLI `config check`: loads and validates everything, resolves watchlist files, and
  dry-run-instantiates every adapter. CI runs it.
- Pinning: adopt `uv` with a committed `uv.lock`; CI installs with `--locked`. Add Renovate or
  Dependabot for bumps.

**Acceptance criteria:**
- An unknown config key fails `config check` with a clear message.
- A literal token placed in a config file is rejected by validation.
- `config check` passes only when every adapter can be instantiated.

---

## P1 — Adapter protocol and shared HTTP layer

**Goal:** New sources are drop-in; every adapter inherits retries, rate limiting, conditional
fetches, and resumability for free.

**New modules:** `src/peptide_watch/adapters/base.py`, `src/peptide_watch/net/client.py`

```python
# adapters/base.py
class RawDocument(NamedTuple):
    source_id: str
    external_id: str          # stable per-record key within the source
    content: bytes            # exact bytes fetched — what gets snapshotted
    content_type: str
    fetched_at: datetime
    meta: dict                # etag, url, http status, etc.

class SourceAdapter(Protocol):
    name: ClassVar[str]
    def fetch(self, ctx: FetchContext) -> Iterator[RawDocument]: ...
    def parse(self, doc: RawDocument) -> Iterator[NormalizedRecord]: ...
    def canonicalize(self, record: NormalizedRecord) -> bytes: ...  # see P2
```

**Design:**
- `fetch` and `parse` are separate, and `parse` is **pure** (bytes in, records out, no I/O).
  This is the single constraint that makes replay (P4) possible.
- `FetchContext` carries the shared HTTP client, the source's cursor, and the run logger.
  Adapters never construct their own sessions.
- Decorator-based registry mapping config `adapter:` strings to classes, plus a
  `list-adapters` CLI command. Entry-points are overkill for a single-repo tool.
- `net/client.py`: one `httpx.Client` wrapper providing tenacity retry with exponential
  backoff + jitter on 429/5xx/transport errors (honoring `Retry-After`); hard connect/read
  timeouts (no infinite hangs); a per-host token-bucket rate limiter with a conservative
  default; automatic conditional GETs from stored etag/last-modified (304 → cursor touch, no
  snapshot write); a fixed honest User-Agent.
- Migrating existing adapters to the protocol is the bulk of the work but is mechanical.

**Acceptance criteria:**
- A new adapter is added by implementing the protocol and registering it — no changes to the
  scan loop.
- A 429 with `Retry-After` is honored; a transient 5xx is retried with backoff; a hung
  connection times out rather than blocking the run.
- A 304 response touches the cursor and writes no snapshot.

---

## P2 — Change detection done right

**Goal:** No duplicate alerts on re-scan, no false positives from volatile markup, no missed
real changes.

**Design:**
- **Two hashes per snapshot:** `raw_sha256` (exact bytes, for storage integrity/dedup) and
  `canonical_sha256` (over the adapter's `canonicalize()` output). Canonicalization is
  per-adapter: sort JSON keys, drop known-volatile fields (timestamps, view counts), collapse
  whitespace; HTML sources must declare a content selector and strip nav/script.
- **Field-level diffing** on `NormalizedRecord`, not bytes: compare only the configured
  tracked fields against the previous stored record. Emit one event per `(record, field)`
  change with `old_value`/`new_value` captured as review evidence.
- **Event identity is a real unique key** with idempotent insertion:

```sql
CREATE UNIQUE INDEX ux_event_identity ON events
  (source_id, external_id, event_type, field, old_hash, new_hash, run_id);
```

- **Disappearance with hysteresis:** a record absent from a fetch increments `miss_count`;
  only after N consecutive misses (default 3) emit `record_disappeared`. Reappearance resets
  the counter. Kills flapping from partial API responses.
- **Parser versioning:** every adapter declares `parser_version: int`, stored per record. When
  a canonical-hash change is caused purely by a parser upgrade (raw bytes identical), suppress
  the event.

**Known issue carried into this design — read before implementing.** The original identity key
was `(source_id, external_id, event_type, field, old_hash, new_hash)`. That silently drops a
**legitimate repeated transition**: if a field cycles A→B, then later A→B again, both events
share the same `(old_hash, new_hash)` and `INSERT OR IGNORE` discards the second. The fix
above adds `run_id` to the index so identical transitions in different runs are preserved while
duplicates within the same run/resume/replay are still deduped. Decide explicitly whether you
want per-run uniqueness (recommended) or true value-cycle dedup; do not leave it implicit.

**Acceptance criteria:**
- Re-scanning unchanged content produces zero new events.
- A volatile timestamp embedded in source content does not produce an event.
- A field cycling A→B→A→B emits an event for each genuine B-transition.
- A record missing for fewer than N scans does not emit `record_disappeared`.

---

## P3 — Alert pipeline: outbox, dedup, tiers, batching

**Goal:** Scanning never blocks on the alert channel; an outage loses nothing; no duplicate or
noisy alerts.

**Pattern:** transactional outbox. The scan writes events to the DB; a separate `deliver`
phase reads undelivered events and sends them.

```sql
CREATE TABLE deliveries (
  event_id  INTEGER PRIMARY KEY REFERENCES events(id),
  channel   TEXT NOT NULL,
  status    TEXT NOT NULL CHECK (status IN ('pending','sent','suppressed','failed')),
  attempts  INTEGER NOT NULL DEFAULT 0,
  sent_at   TEXT,
  last_error TEXT
);
```

**Design:**
- Severity tiers assigned by config rules at event creation (e.g. watchlist hit → high,
  tracked-field change → medium, disappearance → low; per-source overrides). High → immediate
  message; medium/low → swept into the digest.
- Batching: immediate-tier events from one run for one source coalesce into a single message
  (one message per source per run max), with 429-aware retry.
- A channel outage just leaves `pending` rows for the next sweep — nothing is lost.
- Dedup is structural via the P2 identity index; `deliveries` adds a second layer so an event
  is delivered at most once per channel.

**Acceptance criteria:**
- With the alert channel unreachable, events persist as `pending` and send on the next sweep.
- Multiple high-severity events from one source in one run produce one batched message.
- Re-running `deliver` with no new events sends nothing.

---

## P4 — Backfill and replay from snapshots

**Goal:** Re-derive events from stored bytes with zero network — for parser fixes, new tracked
fields, and rebuilds.

**Design:**
- Snapshots stored **content-addressed**: blob keyed by `raw_sha256` (dedupes identical
  fetches), with a manifest row per fetch:
  `(source_id, external_id, fetched_at, raw_sha256, canonical_sha256, parser_version)`.
- `replay` CLI: `peptide-watch replay --source X --since DATE [--parser-upgrade]`. Iterates
  manifest rows in `fetched_at` order, runs current `parse`/`canonicalize`/diff over stored
  bytes — no network. Runs in a flagged replay run; new events are created `suppressed` in
  `deliveries` by default so replay never spams the channel; `--deliver` overrides.
- Unlocks: re-extracting after a parser fix, adding a tracked field retroactively, rebuilding
  the records table (`replay --rebuild`), and testing adapter changes against real history.

**Acceptance criteria:**
- A replay over historical snapshots produces no network calls.
- Replay by default sends no alerts.
- Rebuilding from snapshots reproduces the current records table.

---

## P6 / P7 — Migrations and integrity

**Migrations:** a hand-rolled runner (~60 lines, no SQLAlchemy dependency): numbered SQL files
in `schema/migrations/`, applied transactionally, tracked via `PRAGMA user_version`. Add a CI
test that builds a DB from migration `0→N` and asserts it matches `schema/schema.sql`. Every
schema change in this report becomes a migration from day one.

**Snapshot immutability — enforced, not promised:**

```sql
CREATE TRIGGER snapshots_no_update BEFORE UPDATE ON snapshots
  BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
CREATE TRIGGER snapshots_no_delete BEFORE DELETE ON snapshots
  BEGIN SELECT RAISE(ABORT, 'snapshots are immutable'); END;
```

Plus a `verify` CLI command that re-hashes every stored blob against its `raw_sha256` and
reports corruption — run weekly via the scheduler.

**Acceptance criteria:**
- Migrating a fresh DB `0→N` yields a schema matching `schema.sql`.
- An attempt to UPDATE or DELETE a snapshot row is rejected.
- `verify` detects a deliberately corrupted blob.

---

## P8 — CI language gate (product-rule regression test)

**Goal:** Make the "no recommendations / advice; public sources only" product rule a test that
fails the build, not a convention.

**Design:**
- `tools/check_language.py` + `tools/forbidden_language.txt` (regexes you maintain). Seed
  patterns: `\brecommend(s|ed|ation)?\b`, `\badvice\b`, `\byou should\b`, `\b(take|use) this\b`.
- Scan **user-facing surfaces only**: alert/digest template files, and string literals in
  designated modules (`alerts/`, `digest/`, CLI output) via `ast.walk` over `ast.Constant`
  nodes — not the whole repo, so comments and test fixtures don't false-positive.
- Inline `# lang-ok: <reason>` escape hatch for legitimate uses (e.g. help text stating the
  tool never provides recommendations); allowlist that exact sentence.
- A GitHub Actions job runs it alongside `config check`, lint, and `pytest`; non-zero fails
  the build.

**Acceptance criteria:**
- A recommendation-style phrase added to an alert template fails CI.
- The same phrase inside a code comment or test fixture does not fail CI.
- An allowlisted help-text sentence passes.

---

## Resolved design decisions

**Resume policy:** Auto-resume *interrupted* runs on the next scheduled run (self-healing is
what you want from an unattended job); let the circuit breaker handle chronically failing
sources so they don't retry forever. Provide a `--no-resume` override for debugging.

**Cursor serialization:** The common public APIs in use here paginate via token strings, page
numbers, or skip/limit offsets — all serialize cleanly to a single opaque `cursor_json` blob.
Confirm per adapter during P1 migration; flag any that can't.

---

## Suggested PR sequence

Each PR is independently shippable and reviewable. Bold = recommended first slice.

| PR  | Contents | Size | Maps to |
|-----|----------|------|---------|
| **PR1** | `settings.py` + `config check` + `uv` lock + SQLite pragmas/backup | small | P0b |
| **PR2** | migrations runner + ledger tables + run/task lifecycle + failure isolation + logging + run summary | medium | P0a, P6 |
| PR3 | `net/client.py` + adapter protocol + migrate one adapter as reference | medium | P1 |
| PR4 | migrate remaining adapters; cursors / conditional GET live | mechanical | P1 |
| **PR5** | canonicalization + two-hash snapshots + event-identity index + hysteresis | medium | P2 |
| PR6 | outbox `deliveries` + tiers + batching + digest rework | medium | P3, P5 |
| PR7 | content-addressed snapshot manifest + replay + verify + immutability triggers | medium | P4, P7 |
| PR8 | language-gate script + CI workflow | small | P8 |

---

## Reconciliation log

**PR1 (2026-06-11).** Findings from diffing the spec against the live repo:

- Typed pydantic config models already existed in `src/peptide_watch/config.py` — no separate
  `settings.py` was needed. The gap was `extra="allow"` on `SourceConfig`/`CompanyConfig` and
  pydantic's default extra-ignore on the rest; all models now use `extra="forbid"`.
  `company_id` was promoted from an undeclared extra key to a declared optional field
  (`company_pages.py` read it via `model_extra`; now a plain attribute).
- There are no config-borne secrets today; the secret scan (`_reject_secret_values`) rejects
  token-shaped values anywhere and secret-named keys whose value is not a `"${ENV_VAR}"`
  reference, so the rule is enforced before any alert channel is added.
- "Adapters" in this codebase are the five client classes in `sources/`
  (`ClinicalTrialsClient`, `FdaClient`, `FederalRegisterClient`, `CompanyPageClient`,
  `SecEdgarClient`); `config check` dry-run-instantiates each.
- SQLite pragmas live in a new `database.connect()` helper (WAL, foreign_keys,
  busy_timeout=5000) used by `init_db`; backup is `peptide-watch backup-db` via `VACUUM INTO`
  (same-day backups are refreshed in place). Source modules still open their own connections —
  migrating them to `connect()` belongs to PR2's ledger work.
- `uv.lock` committed; new `.github/workflows/ci.yml` runs `uv sync --locked`, ruff, pytest,
  and `config check` (the pre-existing `daily-monitor.yml` placeholder is untouched).

**PR2 (2026-06-11).** Findings and adaptations:

- **Task granularity is the five scanner families** (`clinicaltrials`, `fda`,
  `federal_register`, `company_pages`, `sec_edgar`), not the 23 `sources.yaml` entries — the
  existing `scan_*` functions are the smallest independently failable units today. Per-entry
  granularity arrives naturally with the P1 adapter protocol.
- Migrations runner: `src/peptide_watch/migrations.py`, numbered files in
  `schema/migrations/`, tracked via `PRAGMA user_version`, each applied in one transaction
  with rollback on failure. `init_db` runs the legacy in-code column migrations first
  (pre-existing behavior, kept), then `apply_migrations()` — so fresh and legacy DBs converge.
  `0001_run_ledger.sql` creates `runs`, `run_tasks` (with an added `counts_json` column for
  the summary rollup), and `source_cursors` (unused until P1 conditional GETs).
- Orchestrator: `runtime/scan.py` `run_scan()` — flock lockfile (`peptide_watch.lock` next to
  the DB), per-task try/except (only KeyboardInterrupt/SystemExit abort, marking the run
  `interrupted`), stale `running` runs marked `interrupted` at startup, auto-resume of the
  latest interrupted run by default (`--no-resume` to override) re-executing only
  pending/error tasks with `attempt + 1`.
- Circuit breaker: computed from `run_tasks` history (no extra state table) — after 3
  consecutive errors a source is skipped with an exponential cool-down (1, 2, 4, … capped 16
  runs), counted via leading `skipped` rows; a `done` resets the streak.
- JSON logging via stdlib (`JsonLogFormatter`), `run_id`/`source_id` bound through `extra`.
  Run summary rolled up from `run_tasks` into `runs.summary_json`, printed as the CLI
  epilogue (`format_summary`, reusable as digest header).
- ~~**Deferred to PR3/4:** single-transaction-per-source atomicity.~~ **Resolved in PR5** —
  see below. (Closer reading showed per-record write sets were already single-transaction;
  the real gaps were connection-per-record without pragmas and no per-entry failure
  isolation inside a scanner family.)

**PR5 + atomicity fix (2026-06-11).** Findings and adaptations:

- **The two-hash design fixed a live false-positive bug:** `normalize_fda_document`,
  `normalize_company_page`, `normalize_sec_filing`, and `normalize_federal_register_document`
  all overrode the canonical text hash with a hash of the **raw fetched body**, so any
  volatile markup change fired a change event. Now `content_hash` is always canonical (over
  normalized extracted text) and the raw payload is hashed separately into a new
  `raw_sha256` column (records + snapshots, migration `0002`).
- **Event identity** (`src/peptide_watch/events.py`): every event row carries
  `source_id, external_id, field, old_value, new_value, run_id` hashed into an
  `identity_key` with a partial unique index; insertion is `INSERT OR IGNORE`. `run_id` is
  in the key (per-run uniqueness, the recommended option), so A→B→A→B emits one event per
  genuine transition while duplicates within one run/resume are dropped. Stores called
  outside a tracked run get an `adhoc-` run id. Actual values are stored instead of the
  spec's `old_hash/new_hash` — they double as review evidence and are small.
- **Parser versioning:** `PARSER_VERSION` per source module, stored on records/snapshots
  (0 = pre-versioning rows). Suppression rule: canonical hash changed but raw bytes
  identical → silent re-extraction update, no events. Legacy rows with empty `raw_sha256`
  never suppress.
- **Disappearance hysteresis is clinicaltrials-only** (`miss_count`, threshold 3, alert
  fires exactly at the threshold, reset on reappearance), and only on full clean sweeps —
  partial scans or scans with fetch errors record no misses. The other families are
  config-keyed pages or rolling query windows where absence is meaningless; revisit per
  adapter in P1.
- **Atomicity/isolation (the PR2 deviation):** every `scan_*` now opens one
  `database.connect()` connection (WAL/busy_timeout), `init_db` once, and commits once per
  record write-set (record + snapshot + events atomic); a failed entry rolls back cleanly.
  Per-entry try/except inside each family: one bad FDA page / company page / SEC company /
  Federal Register query no longer kills its siblings — errors are collected into
  `result.errors`, surfaced as `source_errors` in the run-task counts, and the task only
  raises (→ circuit breaker) when *every* entry failed. Stores split into path-based
  back-compat wrappers and `write_*(connection, ...)` cores; `source_documents` rows are now
  only written on event-producing paths instead of every fetch.

## Progress checklist

- [x] PR1 — config validation, pinning, SQLite hygiene
- [x] PR2 — run ledger, failure isolation, logging, summary, migrations runner
- [ ] PR3 — adapter protocol + shared HTTP client (one adapter migrated)
- [ ] PR4 — remaining adapters migrated; conditional GET + cursors live
- [x] PR5 — change-detection rework (two-hash, event identity, hysteresis) + per-source transactions/isolation pulled forward from PR3/4
- [ ] PR6 — outbox alert pipeline, severity tiers, batching, digest
- [ ] PR7 — content-addressed snapshots, replay, verify, immutability
- [ ] PR8 — CI language gate

---

## Working with Fable and Claude Code

The practical constraint: Fable 5's biology/chemistry safeguards trip on the repo's domain
content, so Fable cannot reliably read the live codebase — but it *can* read this report,
which is deliberately domain-free. Split the work accordingly:

**Design and review — Fable 5.** Paste a single workstream from this report and ask Fable to
pressure-test the design, surface edge cases, or refine acceptance criteria. It never needs the
repo for this; it reasons from the spec. This is where its long-horizon reasoning earns its
keep.

**Implementation against the live repo — Opus or Sonnet in Claude Code.** These read the whole
repo (domain content included) without the fallback, and mechanical implementation against a
clear spec doesn't need Mythos-tier reasoning. Point Claude Code at the repo and feed it one PR
at a time.

**Reusable implementation prompt (per PR):**

```
Read the repo, then implement <PR-N> from docs/PEPTIDE_WATCH_HARDENING_ROADMAP.md.
First reconcile the spec against the actual code: report any tables, modules, or CLI commands
that already exist or differ from the spec, and propose how to adapt before writing.
Then implement in one focused commit: code + a migration if the schema changes + tests that
prove the acceptance criteria in that section. Run pytest. Do not bundle unrelated changes,
and never weaken the product rule (no recommendations/advice; public sources only).
```
