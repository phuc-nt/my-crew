# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: semver.
Development history at finer grain lives in [docs/journals/](docs/journals/).

## [0.1.0] — 2026-07-18

First installable release. Everything below existed as a clone-and-run system built
across v1–v50 (see journals); 0.1.0 packages it as a product.

### Added
- `my-crew` console script (PyPI package `my-crew`): `--help`, `--version`, and the
  full command surface — `quickstart`, `crew init`, `serve`, `doctor`, `upgrade`,
  `agent *`, `web hash-password`, `sandbox prepull`.
- `my-crew serve`: foreground web + coordinator supervisor for Docker Compose,
  systemd, or a plain terminal. `deploy/docker/` ships a Dockerfile + compose file.
- `MY_CREW_HOME`: user state (.env, registry, profiles, data) resolves to the env
  var, else the git checkout, else `~/.my-crew`. Shipped starter profiles seed into
  a fresh home on first run.
- The wheel bundles the web dashboard (no Node needed to install) and the shipped
  resources (starter profiles, templates, domain packs, examples).
- GitHub Actions CI (secret-free test suite, ubuntu + macos) and an OIDC-based
  PyPI release pipeline.

### Core (pre-0.1.0, summarized)
- Autonomy-first agent harness on LangGraph: every write flows through the Action
  Gateway — hard-coded red lines (Lớp A), autonomous-vs-guarded trust modes,
  kill-switch, dry-run default, dedup, rate-limit, immutable audit log.
- Multi-agent virtual office: browser dashboard + 3D office, one-click staff
  templates, chat-ops, team tasks with review steps, per-task cost tracking.
- Integrations via MCP: Jira, Confluence, Slack (+ GitHub via `gh`), layered
  memory, budget caps, scheduler with per-agent cron.

### Known limitations
- The `deep` sandbox tier (`pip install my-crew[deep]`) needs a Docker daemon and
  is not available *inside* the provided container image.
- The 3 MCP servers require Node at runtime (prepulled in the Docker image;
  installed by `deploy/install.sh` on native installs).
