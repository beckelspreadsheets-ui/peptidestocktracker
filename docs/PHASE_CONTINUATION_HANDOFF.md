# Peptide Watch Phase Continuation Handoff

Use this handoff whenever Seth says to continue the next Peptide Watch HQ phase through Corvus/Codex.

## Mission

Continue the Peptide Watch HQ roadmap one phase at a time, preserving the compliance boundary and the live VPS deployment.

Canonical roadmap:
- Project copy: `/home/openclaw/.openclaw/workspace/peptidestocktracker/docs/HQ_AGENT_ROADMAP.md`
- Shared review copy: `/home/openclaw/.openclaw/workspace/plans/peptide-watch-hq-agent-roadmap-2026-06-12.md`

Current live repo:
- `/home/openclaw/.openclaw/workspace/peptidestocktracker`
- GitHub: `beckelspreadsheets-ui/peptidestocktracker`
- Live VPS service: `peptide-watch-api.service`
- Cockpit: `https://peptide.showcase-designs.com` behind Basic Auth
- Local API/cockpit: `http://127.0.0.1:8000`
- Telegram briefing cron: `peptide-watch-briefing-agent` sends to the `peptide agent` Telegram HQ group through the peptide bot helper, not OpenClaw announcement delivery.

## Start Every Phase With This Baseline Check

```bash
cd /home/openclaw/.openclaw/workspace/peptidestocktracker
git fetch origin master
git status --short --branch
git log -1 --oneline
uv run peptide-watch status
systemctl is-active peptide-watch-api.service
curl -s -o /dev/null -w 'api %{http_code}\n' http://127.0.0.1:8000/api/health
curl -s http://127.0.0.1:8000/ | grep -o '<title>[^<]*</title>'
crontab -l | grep peptide_watch
```

Also check the OpenClaw cron job:
- Name: `peptide-watch-briefing-agent`
- Known job id as of 2026-06-12: `d7e17495-7b8d-4893-bbe0-ad7b5caff5f9`
- Schedule: `45 11,21 * * *` UTC
- Session target: `session:peptide-watch-briefing-agent`
- Delivery mode: `none`; the agent sends via `scripts/peptide_watch_send_telegram.py` using `.env`.

Do not proceed if the baseline is broken unless the phase is explicitly to fix the baseline.

## Compliance Boundary

Never weaken this rule:

**No recommendations. No advice. Public sources only.**

Allowed:
- factual source summaries
- recurrence counts
- source-health notes
- operator workflow memory
- comment-period reminders
- watched/ignored/promoted labels

Forbidden:
- buy/sell/hold language
- price targets
- "undervalued", "good trade", "will run", "high upside"
- peptide usage/dosing/sourcing advice
- private/rumored claims

Any Telegram-bound agent text must pass:

```bash
uv run peptide-watch check-language --stdin
```

Fail closed if it cannot pass.

## Phase Workflow

For each phase:

1. Read `docs/HQ_AGENT_ROADMAP.md`.
2. Identify the next incomplete phase and restate the acceptance criteria.
3. Make the smallest code/config changes needed for that phase.
4. Run the phase-specific verification plus baseline checks.
5. Commit and push project changes to `beckelspreadsheets-ui/peptidestocktracker`.
6. If the plan/handoff changed, update and push `beckelspreadsheets-ui/plans`.
7. Update:
   - `memory/YYYY-MM-DD.md`
   - `MEMORY.md` if the state is long-term important
   - `outbox/YYYY-MM-DD-corvus-peptide-watch-phase-N.md`
8. Report:
   - phase completed
   - files changed
   - tests/checks run
   - current service status
   - blockers or next phase

## Deployment / Restart After Code Changes

Use this after changes that affect Python API, CLI, or dashboard:

```bash
cd /home/openclaw/.openclaw/workspace/peptidestocktracker \
&& git pull --ff-only origin master \
&& uv sync --locked --extra web \
&& if git diff --name-only HEAD@{1}..HEAD | grep -q '^dashboard/'; then (cd dashboard && npm ci && npm run build); fi \
&& sudo systemctl restart peptide-watch-api \
&& sleep 3 \
&& systemctl is-active peptide-watch-api \
&& curl -s -o /dev/null -w 'api %{http_code}\n' http://127.0.0.1:8000/api/health \
&& curl -s http://127.0.0.1:8000/ | grep -o '<title>[^<]*</title>' \
&& uv run peptide-watch config check \
&& uv run peptide-watch status
```

Notes:
- Cron scanner does not need a restart. It uses the current checkout on the next scheduled run.
- If cron scripts change, verify with `crontab -l | grep peptide_watch`.
- If the OpenClaw briefing-agent prompt/schedule changes, update the OpenClaw cron job, not systemd.
- Do not print `.env` values.

## Phase-Specific Handoffs

### Phase 0 - Baseline Stabilization

Goal: prove the live system is reproducible and current.

Acceptance:
- Baseline check passes.
- Source caveats are documented: FDA direct 403, USPTO 403.
- Worktree clean.
- `docs/HQ_AGENT_ROADMAP.md` exists on origin.

### Phase 1 - Telegram HQ Group

Goal: move briefing/control flow into the dedicated `peptidestocktracker` Telegram group.

Status as of 2026-06-12: complete. The group title observed from bot updates is `peptide agent`; `.env` points `PEPTIDE_WATCH_TELEGRAM_CHAT_ID` at that supergroup; the existing peptide bot is used. OpenClaw announcement delivery could not post there because the group has the peptide bot, not the OpenClaw Telegram identity, so the briefing cron now uses `scripts/peptide_watch_send_telegram.py` and `delivery.mode=none`.

Needed input from Seth:
- Telegram group chat id, or permission to derive it from bot updates.
- Confirmation whether to use existing peptide bot or a new bot identity.

Tasks:
- Update `.env` with group chat id only after Seth provides/approves it.
- Send test Telegram delivery to group.
- Update OpenClaw briefing cron delivery target if needed.
- Make direct DM no longer the default briefing destination unless explicitly requested.

Acceptance:
- Test message lands in group.
- Forced briefing-agent run lands in group.
- No secrets printed.
- Daily scheduled briefing still enabled.

### Phase 2 - Command Surface

Goal: implement first useful HQ commands.

Minimum commands:
- `/status`
- `/briefing`
- `/discoveries`
- `/sourcehealth`
- `/watch <entity> [note]`
- `/ignore <entity> [reason]`
- `/why <entity>`

Acceptance:
- Commands respond deterministically.
- Mutating commands write operator state safely.
- Responses use source facts only.
- Telegram-bound text passes language gate.

### Phase 3 - Operator Memory Store

Goal: persist Seth's workflow state.

Tasks:
- Add operator memory SQLite schema or equivalent.
- Add read/write helpers.
- Add backup to weekly hygiene if separate DB.
- Add tests for watch/ignore/promote/cursor behavior.

Acceptance:
- `/watch BHIC` survives service restart.
- `/ignore CohBar` suppresses normal prominence.
- `briefing_cursor` prevents duplicate briefing spam.
- No advice/verdict fields exist in schema.

### Phase 4 - Cockpit Integration

Goal: make dashboard reflect operator memory.

Tasks:
- API endpoints for operator entities.
- Cockpit panels: Seth is watching, ignored/archive filter, deadlines, entity detail.
- Read-only sharing remains safe.

Acceptance:
- Dashboard shows operator state.
- Friends/read-only viewers cannot mutate state.
- Entity pages explain "why surfaced" with source links and run ids.

### Phase 5 - Feedback Loop

Goal: each interaction improves the next briefing.

Acceptance:
- Asking about an entity updates factual attention memory.
- Watched entities appear in a "you're following" section.
- Ignored entities stay quiet unless materially changed.
- Deadlines get factual reminders.
- Agent can explain prioritization without advice.

### Phase 6 - Productization

Goal: package the pattern as reusable public-source catalyst OS.

Acceptance:
- One-week stable soak.
- Clean docs for cloning the architecture.
- No secrets or personal operator memory in reusable template.

## Known Open Issues

- USPTO source returns 403 even with a configured key. Do not hide this.
- FDA direct pages return 403 from VPS; accepted partial loss unless Seth wants proxy work.
- Dashboard npm audit currently reports 1 moderate + 1 high dependency issue.
- `uv run peptide-watch briefing --json` in some docs is stale; actual command is `uv run peptide-watch briefing --format json`.

## Perfect User Prompt To Continue

Seth can paste:

```text
Continue Peptide Watch HQ Phase <N>. Read docs/HQ_AGENT_ROADMAP.md and docs/PHASE_CONTINUATION_HANDOFF.md, run the baseline checks, implement only this phase, verify acceptance criteria, deploy/restart what changed, commit/push, update memory/work log, and report status + next phase. Do not print secrets or weaken the no-advice/public-sources-only rule.
```
