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

1. `uv run peptide-watch runs list` — every run `completed`? Any `failed`?
2. `uv run peptide-watch runs show <run_id>` — per-source errors, circuit-breaker skips,
   and counts. A source that is always `skipped` is dead and needs its URL fixed.
3. Read the digest output (`alerts_outbox/` for the file channel) — is medium/low tier
   too noisy or too quiet? Adjust queries/severities accordingly.
4. End of week: `uv run peptide-watch verify`, then review
   `SELECT COUNT(*) FROM events GROUP BY event_type` for anything unexpected, and check
   for `metadata.discovery = true` company documents — those are new tickers the
   full-text scanner found.
