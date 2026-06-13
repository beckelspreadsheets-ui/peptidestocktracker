# Operations — running peptide-watch unattended

## One-time setup

```bash
uv sync --locked            # reproducible install from uv.lock
uv run peptide-watch config check   # must pass: validates config + source coverage
chmod +x scripts/*.sh
```

Optional environment variables (secrets live here, never in config — enforced by
`config check`):

| Variable | Purpose |
|---|---|
| `PEPTIDE_WATCH_CHANNEL` | Alert channel for the cron pipeline: `file` (default), `console`, or `webhook` |
| `PEPTIDE_WATCH_WEBHOOK_URL` | Discord/Slack-style webhook URL (required for the webhook channel) |
| `PEPTIDE_WATCH_WEBHOOK_FIELD` | JSON field name: `content` (default, Discord) or `text` (Slack) |
| `PEPTIDE_WATCH_SEC_USER_AGENT` | Override the SEC EDGAR user-agent (SEC asks for a contact string) |
| `PEPTIDE_WATCH_USPTO_API_KEY` | Free key from developer.uspto.gov; enables the `uspto_patents` family. Verify once with `peptide-watch uspto-check` — while the key is set, the family joins every scan automatically |

## The pipeline

- `scripts/peptide_watch_daily.sh` — `scan` (all 9 source families, tracked run with
  failure isolation and auto-resume) → `deliver` (critical/high alerts, batched) →
  `digest` (medium/low sweep). Logs to `logs/scan-<timestamp>.log`, pruned after 30 days.
- `scripts/peptide_watch_weekly.sh` — `verify` (re-hash stored payloads) +
  `backup-db` (VACUUM INTO `backups/`, ~2 months retained).

Concurrency is safe: a lockfile blocks overlapping scans, and a crashed or killed run is
marked interrupted and auto-resumed by the next invocation.

## Live VPS baseline

Run the Phase 0 verifier after deploys or before starting a new HQ phase:

```bash
scripts/peptide_watch_baseline.sh
```

It checks the current git commit, config validation, latest tracker status, the local
API/cockpit, scanner crontab, and the OpenClaw briefing-agent cron. It intentionally
prints source-health caveats for the two accepted upstream failures without printing
environment variables or secrets:

- FDA direct pages: expected 403 from the VPS datacenter IP unless proxy work is chosen.
- USPTO patents: expected 403 with the current key/API state.

## Telegram HQ delivery

The HQ briefing cron sends group briefings through the peptide Telegram bot, not
OpenClaw's announcement delivery. OpenClaw's Telegram identity may not be a member of
the HQ group, so the cron agent drafts/checks the briefing and then pipes the final
message into:

```bash
uv run python scripts/peptide_watch_send_telegram.py
```

The helper reads `PEPTIDE_WATCH_TELEGRAM_TOKEN` and
`PEPTIDE_WATCH_TELEGRAM_CHAT_ID` from `.env`, runs the shared language gate before
sending, and never prints token or chat-id values. The OpenClaw cron job
`peptide-watch-briefing-agent` should keep `delivery.mode` set to `none`; its final
run summary records `SENT run_id=<id> via peptide bot` after the bot send succeeds.

## Telegram HQ commands

The HQ group command surface is deterministic and repo-native. The CLI entrypoint is:

```bash
uv run peptide-watch hq-command "/status"
uv run peptide-watch hq-command "/watch BHIC public filing recurrence"
```

The Telegram bot long-poller is:

```bash
uv run python scripts/peptide_watch_telegram_commands.py --skip-existing
```

In production it runs as `peptide-watch-commands.service` from
`deploy/peptide-watch-commands.service`. It reads the same `.env` Telegram token/chat id,
ignores messages outside the configured HQ group, replies only to slash commands, and checks
every response with the shared language gate before sending. Mutating commands write only
operator workflow state to `data/operator_state.db`; scanner facts, source documents, raw
blobs, events, and deliveries are never changed by commands.

Current commands:

```text
/status
/briefing
/discoveries
/sourcehealth
/deadlines
/watch <entity> [note]
/ignore <entity> [reason]
/promote <entity> [note]
/archive <entity> [reason]
/why <entity>
/notes <entity>
/setpriority <entity> low|normal|high
```

## Scheduling on a VPS (recommended) — cron

Twice daily around the US market (pre-open and post-close), weekly hygiene on Sundays.
Times in UTC:

```cron
20 11 * * * /opt/peptidestocktracker/scripts/peptide_watch_daily.sh
20 21 * * * /opt/peptidestocktracker/scripts/peptide_watch_daily.sh
0  7  * * 0 /opt/peptidestocktracker/scripts/peptide_watch_weekly.sh
```

Put environment variables in the crontab header (or a `/etc/cron.d/` file):

```cron
PEPTIDE_WATCH_CHANNEL=webhook
PEPTIDE_WATCH_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

VPS notes:

- Any 1-vCPU / 1 GB box is plenty; the tool is a short-lived CLI + SQLite file.
- Install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`), clone the repo to
  `/opt/peptidestocktracker`, run the one-time setup.
- **No domain or web server is needed.** The tracker has no web component; alerts leave
  via the webhook/file channel. A domain only becomes relevant if the separate website
  (docs/WEBSITE_PRD.md) is built later.
- Some commercial sites rate-limit or block datacenter IPs more aggressively than
  residential ones. The run summary makes this visible (per-source errors / circuit
  breaker skips) — check `runs list` in the first soak days and drop or replace any
  source that a given host consistently blocks.

## Scheduling on macOS — launchd

cron on macOS does not run while the machine sleeps. If the Mac is the host, use launchd
(runs missed jobs on wake). Save as
`~/Library/LaunchAgents/com.peptidewatch.daily.plist`, then
`launchctl load ~/Library/LaunchAgents/com.peptidewatch.daily.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.peptidewatch.daily</string>
  <key>ProgramArguments</key>
  <array><string>/Users/andrewferguson/peptidestocktracker/scripts/peptide_watch_daily.sh</string></array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>20</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>20</integer></dict>
  </array>
  <key>StandardErrorPath</key><string>/tmp/peptidewatch.err</string>
</dict></plist>
```

## Soak-week checklist

Each day or two:

0. `uv run peptide-watch status` — one-glance health: latest run, per-source errors,
   storage. Exits non-zero if the latest run failed (cron/monitoring can alert on it).
1. `uv run peptide-watch runs list` — every run `completed`? Any `failed`?
2. `uv run peptide-watch runs show <run_id>` — per-source errors, circuit-breaker skips,
   and counts. A source that is always `skipped` is dead and needs its URL fixed.
3. Read the digest output (`alerts_outbox/` for the file channel) — is medium/low tier
   too noisy or too quiet? Adjust queries/severities accordingly.
4. End of week: `uv run peptide-watch verify`, then review
   `SELECT COUNT(*) FROM events GROUP BY event_type` for anything unexpected, and check
   for `metadata.discovery = true` company documents — those are new tickers the
   full-text scanner found.
