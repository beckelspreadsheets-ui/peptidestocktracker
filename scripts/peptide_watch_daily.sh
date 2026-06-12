#!/usr/bin/env bash
# Daily pipeline: scan -> deliver immediate alerts -> sweep digest.
# Safe to run under cron/launchd; concurrent runs are blocked by the
# scan lockfile and interrupted runs auto-resume on the next invocation.
set -uo pipefail

# launchd/cron give a minimal PATH; make sure uv (Homebrew/local) is found.
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
mkdir -p logs

# Load API keys / webhook URL from a gitignored secrets file if present
# (cron has no interactive shell env). Format: KEY=value lines.
[ -f "$REPO/.env" ] && set -a && . "$REPO/.env" && set +a

CHANNEL="${PEPTIDE_WATCH_CHANNEL:-file}"
STAMP="$(date -u +%Y%m%dT%H%M%S)"
LOG="logs/scan-$STAMP.log"

{
  echo "== scan $STAMP (channel: $CHANNEL)"
  uv run peptide-watch scan
  SCAN_STATUS=$?
  uv run peptide-watch deliver --channel "$CHANNEL"
  uv run peptide-watch digest --channel "$CHANNEL"
  echo "== done (scan exit $SCAN_STATUS)"
  exit "$SCAN_STATUS"
} >>"$LOG" 2>&1
STATUS=$?

find logs -name 'scan-*.log' -mtime +30 -delete
exit "$STATUS"
