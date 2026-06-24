#!/bin/bash
# Wrapper invoked by launchd to run a scheduled report.
# launchd starts with a minimal environment, so set cwd + PATH (node, gh, uv)
# and let the app load .env itself. Usage: run-report.sh --daily|--weekly|--okr|--resource
#
# LEGACY (v2 M1-P3): the three per-report jobs that call this script
# (com.mpm.report.{daily,weekly,resource}.plist) are SUPERSEDED by the coordinating
# service (com.mpm.service.plist), which schedules per-agent workers from each profile's
# cron `schedule:`. After loading com.mpm.service.plist, UNLOAD the three legacy jobs to
# avoid double-scheduling:
#   launchctl unload ~/Library/LaunchAgents/com.mpm.report.daily.plist  (and weekly, resource)
# This script + the 3 plists are kept (not deleted in P3) for the single-agent cron path.
set -euo pipefail

REPO_DIR="/Users/phucnt/workspace/my-project-manager"
cd "$REPO_DIR"

# Ensure tools the report needs are on PATH (node for MCP servers, gh, uv).
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

KIND="${1:---daily}"

# DRY_RUN comes from .env (default true). To post for real on a schedule, set
# DRY_RUN=false in .env. The app reads .env via python-dotenv.
exec /opt/homebrew/bin/uv run python -m src.entrypoints.cron "$KIND"
