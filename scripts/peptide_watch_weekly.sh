#!/usr/bin/env bash
# Weekly hygiene: integrity verification + dated database backup.
set -uo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
mkdir -p logs

[ -f "$REPO/.env" ] && set -a && . "$REPO/.env" && set +a

STAMP="$(date -u +%Y%m%dT%H%M%S)"
LOG="logs/weekly-$STAMP.log"

{
  echo "== weekly $STAMP"
  uv run peptide-watch verify
  VERIFY_STATUS=$?
  uv run peptide-watch backup-db
  uv run peptide-watch prune   # delivered events/source rows older than 180d
  # keep roughly two months of backups and weekly logs
  find backups -name '*.db' -mtime +60 -delete 2>/dev/null
  find logs -name 'weekly-*.log' -mtime +60 -delete 2>/dev/null
  exit "$VERIFY_STATUS"
} >>"$LOG" 2>&1
STATUS=$?
exit "$STATUS"
