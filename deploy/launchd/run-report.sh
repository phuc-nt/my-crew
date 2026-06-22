#!/bin/bash
# Wrapper invoked by launchd to run a scheduled report.
# launchd starts with a minimal environment, so set cwd + PATH (node, gh, uv)
# and let the app load .env itself. Usage: run-report.sh --daily|--weekly|--okr|--resource
set -euo pipefail

REPO_DIR="/Users/phucnt/workspace/my-project-manager"
cd "$REPO_DIR"

# Ensure tools the report needs are on PATH (node for MCP servers, gh, uv).
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

KIND="${1:---daily}"

# DRY_RUN comes from .env (default true). To post for real on a schedule, set
# DRY_RUN=false in .env. The app reads .env via python-dotenv.
exec /opt/homebrew/bin/uv run python -m src.entrypoints.cron "$KIND"
