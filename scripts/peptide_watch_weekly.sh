#!/usr/bin/env bash
# Weekly hygiene: integrity verification + dated database backup.
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
mkdir -p logs

STAMP="$(date -u +%Y%m%dT%H%M%S)"
LOG="logs/weekly-$STAMP.log"

{
  echo "== weekly $STAMP"
  uv run peptide-watch verify
  VERIFY_STATUS=$?
  uv run peptide-watch backup-db
  # keep roughly two months of backups
  find backups -name '*.db' -mtime +60 -delete 2>/dev/null
  exit "$VERIFY_STATUS"
} >>"$LOG" 2>&1
STATUS=$?
exit "$STATUS"
