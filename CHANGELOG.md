# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) · Versioning: semver.
Development history at finer grain lives in [docs/journals/](docs/journals/).

## [0.3.0] — 2026-07-19

UI discipline + a Vietnamese/English language mode for the dashboard.

### Added
- **Language toggle (VN/EN)** in the header, next to the theme and lens toggles.
  Every static interface string switches; backend-origin messages (health checks,
  API errors) and LLM-authored content stay Vietnamese, and technical terms
  (Captures, Guardrail, PIC, deep_agent, engine, tokens…) stay English in both. Zero
  external i18n library — a typed dictionary where a missing translation is a compile
  error.
- **Shared UI primitives** (Button, Card, Badge, Input, EmptyState, PageHeader) so
  every screen draws buttons, cards, badges, and headers from one place; the
  stylesheet gained a section structure and a rule against ad-hoc component classes.

### Changed
- One cost format app-wide (4 decimals under $1, 2 from $1) and one timestamp format.

### Fixed
- The office error-state colour now inverts correctly in dark mode (was pinned to a
  literal); mobile header no longer overflows once the language chip is present.

## [0.2.0] — 2026-07-18

Office dual-lens: one office screen serving both the CEO (normal) and the maintainer
(technical) through a header lens toggle.

### Added
- **Failure & review visuals** in the 3D office: a failed step now paints a red desk +
  ⚠ bubble (previously it silently went idle); a peer-review verdict flashes a floor
  ring (green passed / orange needs-rework).
- **Technical mode** (👁/🔬 header toggle): sandbox-tier 🔒 badges, a health strip
  (coordinator heartbeat + integration checks + fleet budget), a Desk Inspector drawer
  (step, engine tier, cost-so-far), a **Captures** telemetry explorer, and a full-text
  **history search** box. Mode is view-layer only — never a permission gate.
- Read-only observability API: `GET /api/budget`, `/api/captures` (+ `/{id}`),
  `/api/search`.

### Fixed
- launchd services now get a PATH that includes Homebrew + Docker dirs, so the
  coordinator's workers, the MCP watchers, and the deep_agent sandbox find
  `node`/`docker`/`gh`/`gws` (regression from the v0.1.0 `src`→`my_crew` rename).
- A superseded worker's late `failed` event no longer paints a false red desk over a
  live retry (the office event now carries its `attempt_id`).

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
