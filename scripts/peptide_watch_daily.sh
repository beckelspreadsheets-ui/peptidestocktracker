#!/usr/bin/env bash
# Daily pipeline: scan -> deliver immediate alerts -> sweep digest.
# Safe to run under cron/launchd; concurrent runs are blocked by the
# scan lockfile and interrupted runs auto-resume on the next invocation.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
mkdir -p logs

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
