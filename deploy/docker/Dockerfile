# my-crew — single-container image: Python app + Node (the 3 MCP servers run as
# stdio child processes of the agent). The deep_agent sandbox tier needs a Docker
# daemon and is NOT available inside this container (documented limitation) — the
# native + tool-calling tiers work fully.
FROM python:3.12-slim

# Node 22 via NodeSource: the MCP servers are modern ESM packages; Debian bookworm's
# node 18 is end-of-life. curl stays installed for the HEALTHCHECK.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# MCP servers in their own layer — versions single-sourced from the pins file
# (layer invalidates exactly when a pin changes).
COPY config/mcp-server-pins.sh /tmp/mcp-server-pins.sh
RUN . /tmp/mcp-server-pins.sh \
 && npm install --prefix /app/.mcp-servers \
      "$JIRA_PKG_NAME@$JIRA_PKG_VERSION" \
      "$CONFLUENCE_PKG_NAME@$CONFLUENCE_PKG_VERSION" \
      "$SLACK_PKG_NAME@$SLACK_PKG_VERSION"

COPY . /app
# Editable install: REPO_ROOT resolves to /app so shipped resources
# (profiles/templates, domain-packs, registry.example.yaml) are found; user state
# goes to the /data volume via MY_CREW_HOME.
RUN pip install --no-cache-dir -e .

ENV MY_CREW_HOME=/data \
    BIND_HOST=0.0.0.0 \
    PORT=8765 \
    JIRA_MCP_DIST=/app/.mcp-servers/node_modules/mcp-jira-cloud-server/dist/index.js \
    CONFLUENCE_MCP_DIST=/app/.mcp-servers/node_modules/confluence-cloud-mcp-server/dist/index.js \
    SLACK_MCP_DIST=/app/.mcp-servers/node_modules/slack-browser-mcp-server/dist/index.js

VOLUME /data
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8765/health || exit 1

CMD ["my-crew", "serve"]
