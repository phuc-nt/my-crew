#!/bin/bash
# v6 M16: back up all mutable state to a timestamped tar. Excludes .env (secrets) —
# secrets are restored by hand from a password manager, NEVER from a backup archive (R4).
#
#   ./deploy/backup.sh [dest-dir]     # default dest: ./backups/
#
# Backs up: .data/ (per-agent sqlite + audit + tasks), profiles/, registry.yaml, company-docs/.
# For a daily cron:  0 2 * * *  /path/to/deploy/backup.sh /path/to/backups
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
DEST="${1:-$REPO_DIR/backups}"
mkdir -p "$DEST"

# Timestamp is passed in by the caller's clock (date is fine in a shell script, unlike the
# agent runtime). UTC to avoid DST ambiguity in filenames.
STAMP="$(date -u +%Y%m%d-%H%M%S)"
ARCHIVE="$DEST/mpm-backup-$STAMP.tar.gz"

# --exclude .env at every level; tar the state dirs that exist.
PATHS=()
[ -d .data ] && PATHS+=(.data)
[ -d profiles ] && PATHS+=(profiles)
[ -f registry.yaml ] && PATHS+=(registry.yaml)
[ -d company-docs ] && PATHS+=(company-docs)  # M19: the shared company-doc library
if [ "${#PATHS[@]}" -eq 0 ]; then
  echo "nothing to back up (no .data/ profiles/ registry.yaml/ company-docs/)"; exit 0
fi

tar --exclude='.env' --exclude='*/.env' -czf "$ARCHIVE" "${PATHS[@]}"
echo "backup → $ARCHIVE"
echo "  contents: ${PATHS[*]}  (.env excluded)"
