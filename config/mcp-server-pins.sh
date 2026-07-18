# Single source of truth for the 3 MCP-server npm pins (no secrets here).
# Readers: deploy/install.sh (sourced), deploy/docker/Dockerfile (sourced at build),
# `my-crew doctor` (parses KEY=VALUE lines). Exact versions — a re-run resolves
# identically. Plain assignments only: must stay `sh`-sourceable AND trivially
# parseable.
JIRA_PKG_NAME=mcp-jira-cloud-server
JIRA_PKG_VERSION=4.2.0
CONFLUENCE_PKG_NAME=confluence-cloud-mcp-server
CONFLUENCE_PKG_VERSION=1.5.0
SLACK_PKG_NAME=slack-browser-mcp-server
SLACK_PKG_VERSION=1.3.0
