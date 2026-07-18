#!/bin/bash
# v6 M16 / hardened v10 M26: one-command production install for the whole system (Mac / launchd).
#
#   ./deploy/install.sh
#
# Does, in order:
#   1. preflight          — fail loud with the exact fix if a required tool is missing
#   2. uv sync            — install Python deps into the venv
#   3. build the web SPA  — into a temp dir, then swap atomically (never breaks a live server)
#   4. MCP servers        — install the 3 stdio servers (idempotent; honors *_MCP_DIST)
#   5. .env preflight     — copy the template on first run (secrets go in the browser wizard)
#   6. launchd services   — install/reload ONLY when the plist or SPA actually changed
#   7. health gate        — report what is / isn't ready before declaring success
#
# MCP servers install from npm (exact pinned versions, into a repo-local ./.mcp-servers prefix)
# once the 3 packages are published; pass --mcp-dev to clone+build the repos locally instead
# (dev path against unpublished/edited server code). Until the npm packages are published, the
# script always uses clone+build regardless of --mcp-dev (see MCP_NPM_PUBLISHED below).
#
# Idempotent: re-running when nothing changed is a no-op — it does NOT restart the coordinator
# (which would kill in-flight agent runs) or the web service (which would drop sessions). It only
# reloads a service when its plist changed, and only rebuilds/swaps the SPA when the build differs.
# Does NOT write secrets — you fill .env yourself (browser wizard + the preflight output).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"
# launchd needs an absolute uv path baked into the plists; Apple-Silicon brew, Intel
# brew and manual installs differ, so resolve it here instead of hardcoding.
UV_BIN="$(command -v uv || echo /opt/homebrew/bin/uv)"

# v18: registry.yaml là user data (gitignored) — lần cài đầu tạo từ template.
# Idempotent: KHÔNG bao giờ đè registry đang có (đội thật của CEO).
if [ ! -f registry.yaml ] && [ -f registry.example.yaml ]; then
  cp registry.example.yaml registry.yaml
  echo "→ registry.yaml tạo từ registry.example.yaml (lần đầu)"
fi

# --mcp-dev opts into the clone+build MCP install path instead of npm. bash 3.2 (macOS
# system bash) has no getopts long-flag support worth the complexity here — a plain loop
# is simplest (KISS) for a single boolean flag.
MCP_DEV=0
for arg in "$@"; do
  [ "$arg" = "--mcp-dev" ] && MCP_DEV=1
done

# The 3 MCP servers are published to npm, so npm install is the default source. --mcp-dev
# forces clone+build for developing against unpublished/edited server code. (This flag exists
# so a future maintainer with unpublished servers can set it back to 0 without deleting code.)
MCP_NPM_PUBLISHED=1
if [ "$MCP_NPM_PUBLISHED" -eq 1 ] && [ "$MCP_DEV" -eq 0 ]; then
  MCP_SOURCE="npm"
else
  MCP_SOURCE="clone"
fi

echo "== my-crew install =="
echo "repo: $REPO_DIR"

# ---------------------------------------------------------------------------------------------
# [1/7] preflight — required tools. We do NOT auto-install onto the user's machine; we fail loud
# with the exact command so nothing runs half-configured (KISS: the user stays in control).
# ---------------------------------------------------------------------------------------------
echo
echo "[1/7] preflight (required tools)"
missing=0
require() { # name  install-hint
  if command -v "$1" >/dev/null 2>&1; then
    echo "  ✓ $1"
  else
    echo "  ✗ $1 not found — install it:  $2"
    missing=1
  fi
}
require uv  "curl -LsSf https://astral.sh/uv/install.sh | sh"
require node "brew install node"
require npm  "brew install node"
require git  "brew install git"
if [ "$missing" -ne 0 ]; then
  echo
  echo "  Install the tools above, then re-run ./deploy/install.sh"
  exit 1
fi
# gh is only needed for GitHub reads and its login is interactive — don't hard-block install on
# it (a Jira/Confluence-first operator can set gh up later). The health gate reports it at the end.
if command -v gh >/dev/null 2>&1; then
  echo "  ✓ gh"
else
  echo "  • gh not found (optional now) — for GitHub reads: brew install gh && gh auth login"
fi

echo
echo "[2/7] uv sync"
uv sync

# ---------------------------------------------------------------------------------------------
# [3/7] build the web SPA into a TEMP dir (vite --outDir override), then swap into the served dir
# only if the output actually differs. Building straight into my_crew/server/static/app/ — which
# vite.config.ts does by default with emptyOutDir:true — would first WIPE the live-served dir and
# then rewrite it, handing a client a 404/partial bundle mid-build. Building to a temp dir and
# rsync-ing in place avoids that window and lets us skip the web restart when the SPA is unchanged
# (F6). The rsync --delete makes the served dir exactly match the fresh build.
# ---------------------------------------------------------------------------------------------
echo
echo "[3/7] build web SPA"
SPA_DIR="my_crew/server/static/app"
SPA_TMP="$(mktemp -d "${TMPDIR:-/tmp}/mpm-spa.XXXXXX")"
spa_changed=0
# Fingerprint a build dir by RELATIVE-path + content, so a dir hashes the same regardless of where
# it lives (the temp build vs the served dir have different absolute prefixes). Without stripping
# the base dir, the two fingerprints would ALWAYS differ and F6 would restart web on every run.
spa_fingerprint() { # dir
  ( cd "$1" 2>/dev/null && find . -type f -exec shasum {} \; | sort | shasum | cut -d' ' -f1 )
}
if [ -f "$SPA_DIR/index.html" ]; then
  before="$(spa_fingerprint "$SPA_DIR")"
else
  before="none"
fi
# Build into the temp dir (override vite's outDir). The live dir is untouched until the swap.
( cd web && npm install --silent && npm run build -- --outDir "$SPA_TMP" --emptyOutDir )
after="$(spa_fingerprint "$SPA_TMP")"
if [ "$before" != "$after" ]; then
  spa_changed=1
  mkdir -p "$SPA_DIR"
  # Atomic-enough for a local single-operator deploy: rsync writes new files then removes stale
  # ones; the served dir is only briefly inconsistent (vs emptyOutDir which starts empty).
  rsync -a --delete "$SPA_TMP/" "$SPA_DIR/"
fi
rm -rf "$SPA_TMP"
echo "  built → $SPA_DIR$( [ "$spa_changed" -eq 1 ] && echo '  (changed, swapped in)' || echo '  (unchanged — live dir untouched)')"

# ---------------------------------------------------------------------------------------------
# [4/7] MCP servers. Honor any *_MCP_DIST already set in .env (a custom location the config
# resolves against) — if that dist exists we do NOT re-install/re-clone by default.
#
# Two source modes (MCP_SOURCE, computed above from --mcp-dev + MCP_NPM_PUBLISHED):
#   npm   — `npm install --prefix .mcp-servers` at EXACT pinned versions (no `^` range), so a
#           re-run resolves to the identical install and is a true no-op. No build step needed.
#   clone — clone+build the 3 repos into $MCP_BASE (unchanged legacy path, kept for local dev
#           against unpublished/edited server code).
# ---------------------------------------------------------------------------------------------
echo
echo "[4/7] MCP servers (Jira / Confluence / Slack) — source: $MCP_SOURCE"
MCP_BASE="${MCP_BASE:-$HOME/workspace}"
NPM_PREFIX="$REPO_DIR/.mcp-servers"
# Pinned exact versions — single-sourced (also read by the Dockerfile and doctor).
. "$REPO_DIR/config/mcp-server-pins.sh"

# Read a *_MCP_DIST override from .env (value only), if present.
env_dist() { [ -f .env ] && grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true; }
# macOS ships bash 3.2 (no associative arrays), so map repo → env-var name / npm pkg name with a
# case (portable).
mcp_env_key() {
  case "$1" in
    jira-cloud-mcp-server) echo "JIRA_MCP_DIST" ;;
    confluence-cloud-mcp-server) echo "CONFLUENCE_MCP_DIST" ;;
    slack-browser-mcp-server) echo "SLACK_MCP_DIST" ;;
  esac
}
mcp_npm_pkg() {
  case "$1" in
    jira-cloud-mcp-server) echo "mcp-jira-cloud-server" ;;
    confluence-cloud-mcp-server) echo "confluence-cloud-mcp-server" ;;
    slack-browser-mcp-server) echo "slack-browser-mcp-server" ;;
  esac
}
mcp_pkg_version() {
  case "$1" in
    jira-cloud-mcp-server) echo "$JIRA_PKG_VERSION" ;;
    confluence-cloud-mcp-server) echo "$CONFLUENCE_PKG_VERSION" ;;
    slack-browser-mcp-server) echo "$SLACK_PKG_VERSION" ;;
  esac
}
# Basic semver compare via `sort -V` (portable enough for X.Y.Z pins; no external deps).
# Returns 0 (true) when $1 < $2.
version_lt() {
  [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -1)" = "$1" ]
}
# Read "version" out of a package.json without a JSON parser (grep is fine for this one field).
pkg_json_version() { # path-to-package.json
  [ -f "$1" ] && grep -m1 '"version"' "$1" | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' || true
}

if [ "$MCP_SOURCE" = "npm" ]; then
  mkdir -p "$NPM_PREFIX"
  # MIGRATION (red-team F5): a machine that already has *_MCP_DIST pointing at an old clone dir
  # keeps that value (no-clobber, below) even after this npm install runs — if that old build is
  # BELOW the target version, warn loudly instead of silently leaving a stale server wired in.
  for repo in jira-cloud-mcp-server confluence-cloud-mcp-server slack-browser-mcp-server; do
    key="$(mcp_env_key "$repo")"
    override="$(env_dist "$key")"
    target_version="$(mcp_pkg_version "$repo")"
    if [ -n "$override" ] && [ -f "$override" ]; then
      override_pkg_json="$(dirname "$override")/../package.json"
      override_version="$(pkg_json_version "$override_pkg_json")"
      if [ -n "$override_version" ] && version_lt "$override_version" "$target_version"; then
        echo "  ! $repo: $key=$override is v$override_version, older than the npm target v$target_version."
        echo "    A newer version is available via npm. To migrate: unset $key in .env and re-run"
        echo "    this installer, or keep your local build by re-running with --mcp-dev."
      else
        echo "  ✓ $repo (using $key=$override, v${override_version:-unknown})"
      fi
      continue
    fi
    echo "  ✓ $repo (resolved via npm prefix — installed below)"
  done
  echo "  npm install --prefix .mcp-servers (exact versions, idempotent) …"
  ( npm install --prefix "$NPM_PREFIX" \
      "mcp-jira-cloud-server@$JIRA_PKG_VERSION" \
      "confluence-cloud-mcp-server@$CONFLUENCE_PKG_VERSION" \
      "slack-browser-mcp-server@$SLACK_PKG_VERSION" --silent ) \
    && echo "  ✓ MCP packages installed from npm" \
    || echo "  ! npm install failed (network/registry?); re-run installer to retry"
  for repo in jira-cloud-mcp-server confluence-cloud-mcp-server slack-browser-mcp-server; do
    key="$(mcp_env_key "$repo")"
    override="$(env_dist "$key")"
    [ -n "$override" ] && [ -f "$override" ] && continue  # already handled above, no-clobber
    pkg="$(mcp_npm_pkg "$repo")"
    dist="$NPM_PREFIX/node_modules/$pkg/dist/index.js"
    if [ -f "$dist" ] && [ -f .env ] && ! grep -qE "^$key=" .env 2>/dev/null; then
      printf '%s=%s\n' "$key" "$dist" >> .env
      echo "    → wrote $key to .env (npm prefix)"
    fi
  done
else
  for repo in jira-cloud-mcp-server confluence-cloud-mcp-server slack-browser-mcp-server; do
    key="$(mcp_env_key "$repo")"
    override="$(env_dist "$key")"
    if [ -n "$override" ] && [ -f "$override" ]; then
      echo "  ✓ $repo (using $key=$override)"
      continue
    fi
    dir="$MCP_BASE/$repo"
    if [ -f "$dir/dist/index.js" ]; then
      echo "  ✓ $repo (already built)"
    else
      echo "  building $repo …"
      [ -d "$dir/.git" ] || git clone -q "https://github.com/phuc-nt/$repo.git" "$dir" || {
        echo "  ! clone $repo failed (network?); re-run installer to retry"; continue; }
      ( cd "$dir" && npm install --silent && npm run build --silent ) \
        && echo "  ✓ $repo built" || echo "  ! build $repo failed; re-run installer"
    fi
    # If MCP_BASE is not the default, the config won't find the dist unless *_MCP_DIST points to it.
    # Write the override into .env (only when absent — never clobber an existing value).
    if [ "$MCP_BASE" != "$HOME/workspace" ] && [ -f "$dir/dist/index.js" ] && [ -f .env ]; then
      if ! grep -qE "^$key=" .env 2>/dev/null; then
        printf '%s=%s\n' "$key" "$dir/dist/index.js" >> .env
        echo "    → wrote $key to .env (custom MCP_BASE)"
      fi
    fi
  done
fi

echo
echo "[5/7] .env setup"
# The First-run Setup Wizard (M17) handles .env keys + password IN THE BROWSER — no manual
# .env editing, and no secret ever passes through this script. If auth is already configured,
# setup is done and the wizard is closed (410).
if [ -f .env ] && grep -q "^WEB_AUTH_PASSWORD_HASH=." .env 2>/dev/null; then
  echo "  auth already configured — setup complete, going straight to login"
else
  [ -f .env ] || cp .env.example .env
  echo "  first run — the browser will open the Setup Wizard to enter keys + set a password"
fi

# ---------------------------------------------------------------------------------------------
# [6/7] launchd services — install/reload ONLY when the rendered plist differs from what's
# installed, OR (for the web service) when the SPA changed. A no-change re-run must not restart
# anything: restarting the coordinator kills in-flight agent runs; restarting web drops sessions.
# ---------------------------------------------------------------------------------------------
echo
echo "[6/7] launchd services (coordinator + web)"
DEST="$HOME/Library/LaunchAgents"
mkdir -p "$DEST"
reload_service() { # plist-name  force-reload(0/1)
  local name="$1" force="$2"
  local src="deploy/launchd/$name" dst="$DEST/$name"
  local rendered; rendered="$(sed -e "s#__REPO_DIR__#$REPO_DIR#g" -e "s#__UV_BIN__#$UV_BIN#g" "$src")"
  local changed=1
  if [ -f "$dst" ] && [ "$rendered" = "$(cat "$dst")" ]; then changed=0; fi
  if [ "$changed" -eq 0 ] && [ "$force" -eq 0 ]; then
    echo "  = $name (unchanged — not restarted)"
    return
  fi
  printf '%s\n' "$rendered" > "$dst"
  launchctl unload "$dst" 2>/dev/null || true
  launchctl load "$dst"
  echo "  ↻ $name ($( [ "$changed" -eq 1 ] && echo 'plist changed' || echo 'SPA changed' ))"
}
reload_service com.mpm.service.plist 0
# Web serves the SPA, so a changed build means it must reload to pick up new static files.
reload_service com.mpm.web.plist "$spa_changed"

# ---------------------------------------------------------------------------------------------
# [7/7] health gate — report readiness before declaring success. No secret values are printed.
# ---------------------------------------------------------------------------------------------
echo
echo "[7/7] health gate"
gate_ok=1
# MCP builds — resolve the same way [4/7] wrote them: env override first, else the source-mode
# default (npm prefix or clone dir).
for repo in jira-cloud-mcp-server confluence-cloud-mcp-server slack-browser-mcp-server; do
  override="$(env_dist "$(mcp_env_key "$repo")")"
  if [ -n "$override" ]; then
    dist="$override"
  elif [ "$MCP_SOURCE" = "npm" ]; then
    dist="$NPM_PREFIX/node_modules/$(mcp_npm_pkg "$repo")/dist/index.js"
  else
    dist="$MCP_BASE/$repo/dist/index.js"
  fi
  if [ -f "$dist" ]; then echo "  ✓ MCP $repo built"; else echo "  ✗ MCP $repo missing — re-run installer"; gate_ok=0; fi
done
# gh auth (the one live check we can do without secrets)
if gh auth status >/dev/null 2>&1; then
  echo "  ✓ GitHub CLI authenticated"
else
  echo "  ✗ GitHub — run 'gh auth login' once (needed for PR/issue reads)"; gate_ok=0
fi
# .env password → whether the setup wizard still needs completing
if grep -q "^WEB_AUTH_PASSWORD_HASH=." .env 2>/dev/null; then
  echo "  ✓ dashboard auth configured"
else
  echo "  • dashboard not yet set up — finish the browser wizard (keys + password)"
fi

echo
PORT_VAL="$(grep -E '^PORT=' .env 2>/dev/null | cut -d= -f2 || true)"
URL="http://127.0.0.1:${PORT_VAL:-8765}"
echo "  Dashboard: $URL"
echo "  Logs:      .data/web.log  .data/service.log"
echo "  Backup:    ./deploy/backup.sh   (daily cron recommended)"
if [ "$gate_ok" -eq 1 ]; then
  echo "  Status:    ✓ all prerequisites ready"
else
  echo "  Status:    some prerequisites missing (see ✗ above) — fix, then re-run this script"
fi
# Give launchd a moment to start the web service, then open the browser (macOS `open`).
sleep 2
if command -v open >/dev/null 2>&1; then
  open "$URL" 2>/dev/null || true
  echo "  → browser opened; follow the Setup Wizard (first run) or log in."
else
  echo "  → open $URL in your browser."
fi
echo
