#!/bin/bash
# Install the launchd jobs for this repo, substituting the real clone path into the
# plist templates (which ship with a __REPO_DIR__ placeholder so the repo can live
# anywhere). Run once after cloning; re-run safely after pulling new plist templates.
#
# Usage:
#   ./deploy/launchd/install.sh              # install the coordinating service (v2, recommended)
#   ./deploy/launchd/install.sh --legacy     # install the 3 single-agent cron jobs instead (v1 path)
#
# The service (com.mpm.service) reads registry.yaml + each profile's cron schedule and
# spawns per-agent workers. The legacy jobs call run-report.sh on a fixed clock for the
# single `default` agent. Do NOT run both — they double-schedule. See run-report.sh header.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEST="$HOME/Library/LaunchAgents"
mkdir -p "$DEST"

if [[ "${1:-}" == "--legacy" ]]; then
  PLISTS=(com.mpm.report.daily.plist com.mpm.report.weekly.plist com.mpm.report.resource.plist)
  echo "Installing LEGACY single-agent cron jobs (run-report.sh on a fixed clock)."
else
  PLISTS=(com.mpm.service.plist)
  echo "Installing the coordinating service (per-agent workers from registry + schedules)."
fi

for name in "${PLISTS[@]}"; do
  src="$SCRIPT_DIR/$name"
  dst="$DEST/$name"
  # Substitute the placeholder with this clone's absolute path. launchd needs absolute
  # paths and does not expand variables, so we bake the path in at install time.
  sed -e "s#__REPO_DIR__#$REPO_DIR#g" -e "s#__UV_BIN__#$(command -v uv || echo /opt/homebrew/bin/uv)#g" "$src" > "$dst"
  # Reload: unload any prior copy (ignore error if not loaded), then load the new one.
  launchctl unload "$dst" 2>/dev/null || true
  launchctl load "$dst"
  echo "  loaded $name -> $dst"
done

echo
echo "Done. Logs go to $REPO_DIR/.data/. Reminder: writes are DRY_RUN by default —"
echo "set DRY_RUN=false in .env to post for real on a schedule."
