#!/usr/bin/env bash
# Verify the live peptide-watch VPS baseline without printing secrets.
set -uo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

API_URL="${PEPTIDE_WATCH_API_URL:-http://127.0.0.1:8000}"
SERVICE="${PEPTIDE_WATCH_API_SERVICE:-peptide-watch-api.service}"
CRON_JOB_ID="${PEPTIDE_WATCH_BRIEFING_CRON_ID:-d7e17495-7b8d-4893-bbe0-ad7b5caff5f9}"
MIN_COMMIT="${PEPTIDE_WATCH_MIN_COMMIT:-903f23e}"

failures=0

section() {
  printf '\n== %s ==\n' "$1"
}

check() {
  local name="$1"
  shift
  section "$name"
  if "$@"; then
    printf 'PASS %s\n' "$name"
  else
    local status=$?
    printf 'FAIL %s (exit %s)\n' "$name" "$status"
    failures=$((failures + 1))
  fi
}

check_git() {
  git fetch origin master >/dev/null 2>&1
  git status --short --branch
  git log -1 --oneline
  git merge-base --is-ancestor "$MIN_COMMIT" HEAD
  test -z "$(git status --porcelain --untracked-files=no)"
}

check_service() {
  systemctl is-enabled "$SERVICE"
  systemctl is-active "$SERVICE"
}

check_api() {
  curl -fsS -o /dev/null "$API_URL/api/health"
  curl -fsS "$API_URL/" | grep -F '<title>peptide-watch · cockpit</title>' >/dev/null
  printf 'api 200\n'
  printf '<title>peptide-watch · cockpit</title>\n'
}

check_crontab() {
  crontab -l | grep -F 'scripts/peptide_watch_daily.sh'
  crontab -l | grep -F 'scripts/peptide_watch_weekly.sh'
}

check_openclaw_cron() {
  timeout 30s openclaw cron get "$CRON_JOB_ID" \
    | python3 -c 'import json, sys
data = json.load(sys.stdin)
assert data["name"] == "peptide-watch-briefing-agent"
assert data["enabled"] is True
assert data["schedule"]["kind"] == "cron"
assert data["schedule"]["expr"] == "45 11,21 * * *"
print("{}: enabled {} {}".format(data["name"], data["schedule"]["expr"], data["schedule"].get("tz", "")).rstrip())'
}

section "source caveats"
printf 'FDA direct pages: expected 403 from VPS datacenter IP unless proxy work is chosen.\n'
printf 'USPTO patents: expected 403 with current key/API state; keep visible in status.\n'

check "git baseline" check_git
check "config check" uv run peptide-watch config check
check "status" uv run peptide-watch status
check "systemd API service" check_service
check "local API/cockpit" check_api
check "scanner crontab" check_crontab
check "OpenClaw briefing cron" check_openclaw_cron

section "baseline result"
if [ "$failures" -eq 0 ]; then
  printf 'PASS baseline\n'
  exit 0
fi

printf 'FAIL baseline (%s failed checks)\n' "$failures"
exit 1
