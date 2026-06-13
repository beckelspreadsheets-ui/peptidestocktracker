# Peptide Watch HQ Agent Roadmap

**Date:** 2026-06-12
**Owner:** Seth + Corvus
**Repo:** `beckelspreadsheets-ui/peptidestocktracker`
**Current VPS commit:** `903f23e Single-port serving + consolidated VPS deploy runbook`
**Current live cockpit:** `https://peptide.showcase-designs.com` behind Basic Auth
**Local/tunnel cockpit:** `http://localhost:8000` via `ssh -i ~/.ssh/hetzner_openclaw -L 8000:localhost:8000 root@100.84.204.30`

## Goal

Turn peptide-watch from a scanner into a research operating system:

1. **Tracker** collects public-source signals and computes deterministic, compliance-safe rankings.
2. **Cockpit** gives Seth and trusted friends a fast visual HQ for scanning the signal field.
3. **Telegram HQ agent** lives in the peptide tracker Telegram group, remembers Seth's research attention over time, and helps manage incoming information without giving investment advice.

The system should learn Seth's workflow, not make trading calls.

## Non-Negotiable Product Rule

No recommendations. No advice. Public sources only.

The agent can say:
- "BHIC appeared again in SEC full-text discovery."
- "This is the third appearance since you marked it watch."
- "FDA direct pages are blocked from the VPS; regulations.gov and openFDA still worked."
- "Comment period closes in 19 days."

The agent cannot say:
- "Buy this."
- "This looks undervalued."
- "This is a strong trade."
- "This will run."
- "You should take/use/source a peptide."

Every outbound Telegram briefing must pass:

```bash
uv run peptide-watch check-language --stdin
```

If the draft fails the gate after three rewrites, it must withhold the briefing and send only the fail-closed fallback from `docs/AGENT_BRIEFING_HANDOFF.md`.

## Current System State

Already live:

- Repo synced to `903f23e`.
- `peptide-watch-api.service` serves API + cockpit on `127.0.0.1:8000`.
- Nginx proxies `https://peptide.showcase-designs.com` to the local cockpit behind Basic Auth.
- Cron scans at `11:20` and `21:20` UTC daily.
- Weekly hygiene runs Sunday `07:00` UTC.
- OpenClaw briefing-agent cron `peptide-watch-briefing-agent` runs `11:45` and `21:45` UTC.
- Forced briefing-agent test delivered to Telegram.
- data.gov/regulations key configured.
- Telegram token/chat id configured.
- USPTO key present but USPTO API returns 403.
- FDA direct pages return 403 from VPS; accepted as datacenter IP block per runbook.

Latest known status:

```text
Latest run:  20260612T203523-98b6257e  [completed]
  sources:   {'done': 11, 'error': 2}
  ERROR fda: 403
  ERROR uspto_patents: 403
Storage: 773 events, 1546 deliveries, 545 blobs (7.5 MB)
```

## Architecture Target

```text
Public sources
  -> peptide-watch scan
  -> SQLite watch DB
  -> deterministic relevance/briefing layer
  -> cockpit API + UI
  -> Telegram HQ agent
  -> agent memory / operator state
  -> better next briefing + dashboard focus
```

There are two separate data stores:

1. **Fact store:** existing tracker SQLite DB. Public-source records, runs, events, deliveries, raw blobs.
2. **Operator memory store:** new small store for Seth's workflow state. This stores attention, tags, notes, ignored/promoted entities, and briefing cursors. It must never store private secrets or investment verdicts.

## Phase 0 - Stabilize Baseline

Purpose: make sure today's deployment is reproducible before adding new behavior.

Tasks:
- Confirm `git log -1` is `903f23e` or later.
- Confirm `uv run peptide-watch config check` passes.
- Confirm `uv run peptide-watch status` exits 0.
- Confirm `peptide-watch-api.service` is enabled/active.
- Confirm `curl http://127.0.0.1:8000/api/health` returns 200.
- Confirm `curl http://127.0.0.1:8000/` returns `<title>peptide-watch · cockpit</title>`.
- Confirm OpenClaw cron `peptide-watch-briefing-agent` exists and is enabled.
- Document current source failures: FDA direct 403, USPTO 403.

Acceptance:
- One command block can verify the whole baseline.
- No secrets printed.
- Repo worktree is clean except intentional local ignored files.

## Phase 1 - Telegram HQ Group

Purpose: move the agent from Seth's direct messages into a dedicated peptide tracker Telegram group.

Setup:
- Seth creates or confirms Telegram group: `peptidestocktracker`.
- Add the peptide Telegram bot to the group.
- Get the group chat id.
- Update `.env`:
  - `PEPTIDE_WATCH_TELEGRAM_CHAT_ID=<group_id>`
  - keep `PEPTIDE_WATCH_TELEGRAM_TOKEN` unchanged unless rotating bots.
- Run:
  ```bash
  set -a && . ./.env && set +a
  uv run peptide-watch deliver --channel telegram
  ```
- Update OpenClaw briefing-agent cron delivery target if needed.

Agent behavior:
- Scheduled briefings post in the HQ group.
- Seth can reply in-thread with follow-up asks.
- The agent should treat the group as operating context but must not leak unrelated personal memory.

Acceptance:
- A test message lands in the group.
- Scheduled briefing lands in the group.
- Seth can use the group as the command center.
- Direct Telegram is no longer the default destination unless explicitly requested.

## Phase 2 - Command Surface

Purpose: give the HQ group practical controls.

Status as of 2026-06-13: complete. Command handling is deterministic and repo-native via
`peptide-watch hq-command`; the Telegram HQ long-poller runs as
`peptide-watch-commands.service`. Operator workflow mutations write to
`data/operator_state.db` only; scanner facts and raw public-source data remain untouched.

Initial commands:

```text
/status
/briefing
/discoveries
/sourcehealth
/deadlines
/watch <entity> [note]
/ignore <entity> [reason]
/promote <entity>
/archive <entity>
/why <entity>
/notes <entity>
/setpriority <entity> low|normal|high
```

Command meanings:
- `/status`: latest run, source health, storage, next scan.
- `/briefing`: fresh briefing from `peptide-watch briefing --format json`.
- `/discoveries`: current non-watchlist filer queue.
- `/sourcehealth`: failing/degraded source families and impact.
- `/deadlines`: open comment periods and known dated catalysts.
- `/watch`: add entity to Seth's followed list.
- `/ignore`: suppress entity from high-prominence briefings unless it materially changes.
- `/promote`: mark discovery as ready to add to watchlist review.
- `/archive`: hide resolved/noisy entity from normal flow.
- `/why`: explain why an entity surfaced, using only tracker facts.
- `/notes`: show Seth's notes and factual recurrence for an entity.
- `/setpriority`: change operator priority, not investment attractiveness.

Implementation choices:
- Start with a lightweight command router in the agent prompt if fastest.
- Move to repo-native CLI/API endpoints once command behavior stabilizes.
- Prefer deterministic handlers for state changes; let the LLM explain facts, not mutate files directly without validation.

Acceptance:
- Each command has a deterministic response shape.
- Mutating commands write operator memory safely.
- Commands never alter source facts or raw scan data.
- Every command response passes the language gate when applicable.

## Phase 3 - Operator Memory Store

Purpose: make the agent learn over time.

Status as of 2026-06-13: complete. Operator memory remains in the separate
`data/operator_state.db` SQLite database created for the HQ command surface, now
with the Phase 3 memory schema: durable entity status/priority/notes,
appearance/source counts, factual entity-event memory, command interactions, and
`briefing_cursor` dedupe. Weekly hygiene backs up the operator DB separately.
Ignored/archived entities are kept out of normal `/briefing` prominence, while
watched/promoted entities are called out factually as operator workflow state.

Recommended store:
- SQLite table in a separate DB, e.g. `data/operator_memory.db`, or tables clearly namespaced away from scanner facts.
- Do not store secrets.
- Do not store buy/sell/hold verdicts.
- Back up during weekly hygiene.

Suggested schema:

```sql
CREATE TABLE operator_entities (
  id INTEGER PRIMARY KEY,
  entity_key TEXT UNIQUE NOT NULL,
  display_name TEXT NOT NULL,
  entity_type TEXT,
  status TEXT NOT NULL, -- watch, ignore, promoted, archived
  priority TEXT NOT NULL DEFAULT 'normal',
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  appearance_count INTEGER NOT NULL DEFAULT 0,
  source_url_count INTEGER NOT NULL DEFAULT 0,
  user_notes TEXT,
  created_by TEXT NOT NULL DEFAULT 'telegram',
  updated_at TEXT NOT NULL
);

CREATE TABLE operator_entity_events (
  id INTEGER PRIMARY KEY,
  entity_key TEXT NOT NULL,
  run_id TEXT,
  event_type TEXT,
  source_family TEXT,
  source_url TEXT,
  observed_at TEXT NOT NULL,
  fact_summary TEXT NOT NULL,
  FOREIGN KEY(entity_key) REFERENCES operator_entities(entity_key)
);

CREATE TABLE operator_interactions (
  id INTEGER PRIMARY KEY,
  message_id TEXT,
  entity_key TEXT,
  command TEXT,
  user_text TEXT,
  response_summary TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE briefing_cursor (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  last_run_id TEXT,
  last_posted_hash TEXT,
  last_posted_at TEXT
);
```

Memory rules:
- Store names, dates, source URLs, statuses, notes, and interaction summaries.
- Store "Seth asked about this" and "Seth ignored this."
- Do not store "good trade", "best pick", "high upside", or similar verdicts.
- Use factual labels: recurring, new, ignored, promoted, followed, deadline-near.

Acceptance:
- `/watch BHIC` persists across restarts.
- Re-running a briefing can say "BHIC is on your watch list" factually.
- Duplicate briefings are suppressed by `briefing_cursor`.
- Memory survives context resets.

## Phase 4 - Cockpit Integration

Purpose: make the dashboard reflect operator state, not just raw tracker data.

Status as of 2026-06-13: complete for the read-only cockpit layer. The API now
exposes read-only operator entity list/detail/deadline endpoints, the main
cockpit includes a "Seth is watching" panel, and `/operator` plus
`/operator/{entity_key}` show followed/promoted/ignored/archived workflow state
with source facts, source links, and run ids. Dashboard mutation endpoints were
intentionally not added; Telegram remains the only operator mutation surface.

Cockpit additions:
- "Seth is watching" panel.
- Ignored/archive filter.
- Entity detail pages.
- Discovery queue with watch/ignore/promote actions.
- Source health strip.
- Deadline countdowns.
- "New since last visit."
- Shareable read-only mode.

Access model:
- Public/trusted friends: read-only cockpit behind Basic Auth or a second read-only auth.
- Seth/admin: can mutate operator memory through Telegram first, then eventually dashboard controls.
- Do not expose mutation endpoints publicly without auth.

API additions:
- `GET /api/operator/entities`
- `GET /api/operator/entities/{entity_key}`
- `GET /api/operator/deadlines`

Acceptance:
- Dashboard loads live API data.
- Read-only users cannot mutate operator state.
- Seth can inspect followed/ignored/promoted entities visually.
- Entity page explains why an item exists with sources and run ids.

## Phase 5 - Agent Feedback Loop

Purpose: make every interaction improve the next briefing.

Loop:
1. Scan completes.
2. Tracker computes deterministic briefing.
3. Agent reads briefing JSON + operator memory.
4. Agent drafts Telegram briefing.
5. Draft passes language gate.
6. Agent posts.
7. Seth reacts or commands.
8. Agent updates operator memory.
9. Next briefing uses that memory for ordering and annotation.

Examples:
- Seth: `/watch BHIC possible 503B angle`
  - Next briefing: "BHIC is on your watch list; latest appearance unchanged since..."
- Seth: `/ignore CohBar too old/noisy`
  - Next briefing: CohBar moves to quiet/ignored unless a material new signal appears.
- Seth: `/why RMTG`
  - Agent explains the filings/source family/peptide mentions, no advice.
- Seth replies "show me deadlines tomorrow"
  - Agent pins deadline cadence, still factual.

Acceptance:
- Memory changes briefing order and labels.
- Memory does not change underlying deterministic source facts.
- Agent can explain its own prioritization.
- Agent remains useful even when there are zero new events.

## Phase 6 - Sharing and Productization

Purpose: make this reusable.

Shareable cockpit:
- Keep `peptide.showcase-designs.com` protected.
- Add read-only friend credentials if desired.
- Consider a "public-safe export" view later with no private operator notes.

Product template:
- Scanner adapters.
- Deterministic scoring.
- Cockpit.
- Learning HQ Telegram agent.
- Compliance/language gate.
- Operator memory.

Potential future verticals:
- Biotech/peptide catalysts.
- Crypto launch surfaces.
- OTC filings.
- Regulatory dockets.
- Real estate permits/code/enforcement.
- Competitor/news intelligence.

Acceptance:
- Peptide system is stable for at least one week.
- Seth uses HQ group for real triage.
- Agent memory improves signal management.
- Architecture can be copied without leaking secrets or personal memory.

## Known Risks and Open Questions

Risks:
- USPTO 403 may require a different key, signup tier, request headers, or proxy.
- FDA direct pages may remain blocked by VPS datacenter IP.
- Telegram group commands need careful permission handling.
- Agent memory can become noisy if every interaction is saved without summarization.
- Dashboard mutation endpoints require real auth before exposure.
- npm audit currently reports 1 moderate + 1 high finding in dashboard dependencies; do not ignore before broader sharing.

Open questions:
- Should the HQ group use the existing Telegram bot or a separate bot identity?
- Should friends get the same cockpit or a sanitized read-only cockpit?
- Does Seth want mutations only through Telegram at first, or dashboard buttons too?
- Which entities should be seeded into the initial watch/ignore/promote memory?
- Should the briefing agent post after both daily scans or only the evening scan once the system stabilizes?

## Reset Handoff

If context is reset, resume from this checklist:

```bash
cd /home/openclaw/.openclaw/workspace/peptidestocktracker
git log -1 --oneline
git status --short
uv run peptide-watch status
systemctl is-active peptide-watch-api.service
curl -s http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/ | grep -o '<title>[^<]*</title>'
crontab -l | grep peptide_watch
```

Also check OpenClaw cron:
- Job name: `peptide-watch-briefing-agent`
- Current job id: `d7e17495-7b8d-4893-bbe0-ad7b5caff5f9`
- Schedule: `45 11,21 * * *` UTC
- Session target: `session:peptide-watch-briefing-agent`

Current next build recommendation:
1. Create Telegram HQ group destination.
2. Add operator memory store.
3. Implement `/watch`, `/ignore`, `/status`, `/briefing`, and `/why`.
4. Wire cockpit to read operator memory.
