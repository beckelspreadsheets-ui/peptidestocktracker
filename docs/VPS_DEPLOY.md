# VPS Deployment Runbook (for an autonomous agent)

You are setting up `peptide-watch` to run unattended on a Linux VPS. It is a Python CLI
that scans public APIs on a schedule and writes alerts to files (or a webhook). Follow these
steps in order. Each step has a verification with expected output — **do not proceed past a
failed verification.** Stop and report if a step fails for a reason not covered in
Troubleshooting.

Context you may need: `docs/PROJECT_STATUS.md` (architecture + state), `docs/OPERATIONS.md`
(ops detail), `docs/ALERT_TAXONOMY.md` (what the alerts mean). Secrets are **never** committed
and **never** printed — they live only in a `chmod 600 .env` file you create in Step 4.

---

## Step 1 — Install uv (the Python runtime/dependency manager)

```bash
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
# ensure uv is on PATH for this shell
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
uv --version
```
**Verify:** `uv --version` prints a version (e.g. `uv 0.5.x`). uv fetches its own Python 3.12+,
so the system Python version does not matter.

## Step 2 — Clone the repository

```bash
cd /opt 2>/dev/null || cd "$HOME"
git clone https://github.com/beckelspreadsheets-ui/peptidestocktracker.git
cd peptidestocktracker
```
**Verify:** `ls docs/PROJECT_STATUS.md` exists. (Use the SSH URL
`git@github.com:beckelspreadsheets-ui/peptidestocktracker.git` instead if HTTPS auth fails
and an SSH deploy key is configured.)

## Step 3 — Install dependencies (reproducible, from the lockfile)

```bash
uv sync --locked
```
**Verify:** ends with `Installed N packages` or `Audited N packages`, no error. This is the
exact command the schedule will rely on.

## Step 4 — Configure secrets (the only step needing human-provided values)

```bash
cp .env.example .env
chmod 600 .env
```
Now edit `.env` and fill in the values the operator gives you. **All keys are optional** —
the tool runs without any of them, just with reduced coverage:

- `PEPTIDE_WATCH_REGULATIONS_API_KEY` — free, instant from https://api.data.gov/signup/ .
  Without it, the `regulations_gov` family uses a shared DEMO_KEY that rate-limits (429s).
  Strongly recommended.
- `PEPTIDE_WATCH_USPTO_API_KEY` — free from https://developer.uspto.gov . Without it, the
  `uspto_patents` family simply does not run (no error).
- `PEPTIDE_WATCH_WEBHOOK_URL` (+ set `PEPTIDE_WATCH_CHANNEL=webhook`) — for phone alerts via
  Discord/Slack. Without it, alerts are written to `alerts_outbox/` files.

**Do NOT** invent key values, commit `.env`, or print its contents. If the operator has not
supplied a key, leave that line commented out and continue.

**Verify:** `git status --porcelain .env` prints nothing (it is gitignored).

## Step 5 — Validate configuration

```bash
uv run peptide-watch config check
```
**Verify:** prints `Config OK: ...` and a `Source coverage:` line, exit 0. If it fails, the
config is broken — report the message; do not work around it.

## Step 6 — One real scan to confirm end-to-end operation

```bash
chmod +x scripts/*.sh
uv run peptide-watch scan
uv run peptide-watch status
```
**Verify:** `scan` prints a summary like `sources: 12 done` (one family, `uspto_patents`,
only appears if its key is set; one `error` line for `regulations_gov` is acceptable if no
data.gov key yet — that is the rate limit, not a failure). `status` prints the latest run as
`[completed]` and a `Storage:` line. This first scan takes a few minutes (polite rate limits).

## Step 7 — Schedule it with cron

```bash
crontab -l 2>/dev/null > /tmp/ct || true
cat >> /tmp/ct <<'CRON'
# peptide-watch: scan twice daily (UTC) around US market open/close + weekly hygiene
20 11 * * * /REPO/scripts/peptide_watch_daily.sh
20 21 * * * /REPO/scripts/peptide_watch_daily.sh
0  7  * * 0 /REPO/scripts/peptide_watch_weekly.sh
CRON
sed -i "s#/REPO#$(pwd)#g" /tmp/ct
crontab /tmp/ct && rm /tmp/ct
crontab -l | grep peptide_watch
```
**Verify:** `crontab -l` shows the three lines with the absolute repo path. The scripts source
`.env` automatically, so secrets do not go in the crontab. The daily script logs to `logs/`,
prunes its own old logs, and is safe against overlap (lockfile).

## Step 8 — Final health report to the operator

Run and report the output of:
```bash
uv run peptide-watch status
uv run peptide-watch runs list --limit 3
uv run peptide-watch discoveries --limit 10
```
Tell the operator: deployment is complete; the scan runs at 11:20 and 21:20 UTC daily; which
keys are configured vs missing; and that `discoveries` is the queue of new companies to review
for the watchlist.

---

## What "healthy" looks like day-to-day

- `uv run peptide-watch status` → latest run `[completed]`, exits 0. (Exits 1 if the last run
  failed — a monitor can alert on that.)
- Alerts accumulate in `alerts_outbox/alerts-YYYYMMDD.md` (file channel) or arrive at the
  webhook.
- `logs/scan-*.log` shows each run; old logs auto-prune (30d). Weekly job verifies integrity,
  backs up the DB, and prunes delivered events >180d.

## Setting up phone alerts (webhook) — optional

By default alerts are written to `alerts_outbox/alerts-YYYYMMDD.md`. For push alerts:

**Telegram (recommended if a TG bot is already in use):** message @BotFather, `/newbot`,
copy the token. Get your chat id: message the new bot once, then open
`https://api.telegram.org/bot<TOKEN>/getUpdates` and read `result[].message.chat.id`. Put in
`.env`:
```
PEPTIDE_WATCH_CHANNEL=telegram
PEPTIDE_WATCH_TELEGRAM_TOKEN=123456:ABC-DEF...
PEPTIDE_WATCH_TELEGRAM_CHAT_ID=123456789
```
Test: `uv run peptide-watch deliver --channel telegram`.

**Discord:** Server → a channel → Edit Channel → Integrations → Webhooks → New Webhook →
Copy URL. Put in `.env`:
```
PEPTIDE_WATCH_CHANNEL=webhook
PEPTIDE_WATCH_WEBHOOK_URL=https://discord.com/api/webhooks/XXXX/YYYY
PEPTIDE_WATCH_WEBHOOK_FIELD=content
```
**Slack:** create an Incoming Webhook at api.slack.com/messaging/webhooks; same as above but
`PEPTIDE_WATCH_WEBHOOK_FIELD=text`.

Test it without waiting for cron: `uv run peptide-watch deliver --channel webhook`. NOTE:
the very first delivery sends the whole backlog (one batched message per source per run) —
expected; afterward only new events send. The webhook URL is a secret — keep it only in
`.env`.

## Troubleshooting

- **`uv: command not found` in cron** — the scripts already export a PATH covering
  `~/.local/bin`. If uv installed elsewhere, add its dir to the `export PATH` line at the top
  of `scripts/peptide_watch_daily.sh` and `_weekly.sh`.
- **`regulations_gov` errors with 429** — expected without a data.gov key; harmless (other
  families still complete). Add `PEPTIDE_WATCH_REGULATIONS_API_KEY` to `.env` to fix.
- **`fda` family returns 403 / connection blocked** — fda.gov sits behind a WAF (Akamai) that
  may block a datacenter IP. The HTTP client auto-retries blocked hosts through a different
  TLS stack (urllib), which fixes *fingerprint* blocks; a pure *IP* block it cannot. First,
  confirm it is actually failing in a real scan (not just a manual curl):
  `uv run peptide-watch fda scan` then `uv run peptide-watch runs show <id>`. If still blocked:
  1. **Accept the partial loss** — this is the recommended default. The FDA *regulatory
     signal* is redundant: PCAC/503A/503B/compounding activity also arrives via
     `regulations_gov` (regulations.gov), `federal_register` (federalregister.gov), and
     `openfda_enforcement`/`openfda_shortages` (api.fda.gov) — all different hosts that are
     not usually IP-blocked. The circuit breaker auto-skips the blocked `fda` pages after 3
     failures, so they become quiet, not noisy.
  2. **Or route through a proxy** — the client honors standard proxy env vars. Add to `.env`:
     `HTTPS_PROXY=http://user:pass@proxy-host:port` (a residential proxy avoids datacenter
     blocks). All traffic then uses it; set `NO_PROXY=clinicaltrials.gov,api.fda.gov` to
     exclude hosts that already work, if you want to minimize proxy usage.
- **A source repeatedly `skipped`** in `runs show` — the circuit breaker tripped after 3
  consecutive failures (e.g. a host blocking the VPS IP). Inspect the error; the source self-
  retries after a cooldown. Not fatal.
- **`config check` fails** — a `sources.yaml` entry has no scanner family. Report it; do not
  edit config to bypass.
- **Clone auth fails** — try the SSH URL with a deploy key, or have the operator make the repo
  accessible. Do not embed credentials in the repo.

## Hard rules

- Never commit `.env`, API keys, tokens, or `data/*.db`. They are gitignored — keep it that way.
- Never weaken the product rule (no recommendations/advice; public sources only). The CI
  language gate (`tools/check_language.py`) enforces it.
- Secrets come from the operator and live only in `.env` (chmod 600). Do not print them.
