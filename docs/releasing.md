# Releasing my-crew

Versioning: semver, single source of truth in `pyproject.toml` (`version = "X.Y.Z"`).
`my-crew --version` reads installed metadata (`importlib.metadata`).

## What a release artifact contains

`uv build` produces a wheel with:
- the `my_crew` package, including the committed FE dist (`my_crew/server/static/app/`) —
  installing the wheel needs NO Node;
- shipped resources under `my_crew/_shipped/` (starter profiles, templates,
  domain-packs, registry/config examples, model prices) via the pyproject
  `force-include` map — `settings.SHIPPED_ROOT` resolves them there; a checkout
  resolves the same files at the repo root.

Node IS still required at runtime for the 3 MCP servers (Jira/Confluence/Slack) —
see the deployment guide.

## Cutting a release

1. Ensure main is green (CI: BE pytest + ruff + FE vitest/tsc/build), then run
   `scripts/cold-start-smoke.sh --browser` — CI never installs the wheel, so a
   packaging break (missing `_shipped/`, stale FE dist) passes CI and fails the user.
2. If FE changed since the last dist rebuild: `cd web && npm run build`, commit the
   regenerated `my_crew/server/static/app/` (the wheel ships whatever is committed).
3. Bump `version` in `pyproject.toml`; update `CHANGELOG.md`.
4. Commit, then tag: `git tag -a vX.Y.Z -m "..." && git push origin main vX.Y.Z`.
5. The `release` GitHub Actions workflow builds the wheel from the tag and publishes
   to PyPI via **OIDC trusted publishing** (no stored token). First-time setup:
   register the repo as a trusted publisher on pypi.org (project `my-crew`,
   workflow `release.yml`) — an account-owner action in the PyPI web UI.

## Manual fallback (no CI)

```bash
uv build --out-dir /tmp/my-crew-release
# verify: unzip -l /tmp/my-crew-release/*.whl | grep -c _shipped/   (expect ~66)
uv publish --index testpypi /tmp/my-crew-release/*   # rehearse on TestPyPI first
uv publish /tmp/my-crew-release/*
```

## Verify an install

Automated (preferred) — builds a wheel, installs it into a throwaway venv against a fresh
`MY_CREW_HOME`, and asserts what only a clean machine can catch: `_shipped/` resources and
the committed FE bundle actually landed in the wheel, an empty home seeds itself, `/health`
answers, and the served page carries a bundle. Self-cleaning, no network, no secrets; runs
on its own port so it never touches a live service.

```bash
scripts/cold-start-smoke.sh              # backend only (~1 min)
scripts/cold-start-smoke.sh --browser    # + a real chromium load of the installed bundle
```

The `--browser` pass runs `web/e2e-cold-start/` under `playwright.cold-start.config.ts` —
a separate config from the mocked smoke suite on purpose: here the backend is the REAL one
just installed, which is the whole point.

Manual equivalent:

```bash
python -m venv /tmp/v && /tmp/v/bin/pip install my-crew
MY_CREW_HOME=/tmp/crew-home /tmp/v/bin/my-crew agent list   # seeds + bootstraps
MY_CREW_HOME=/tmp/crew-home /tmp/v/bin/my-crew serve --web-only  # /health → 200
```

## Benchmarking a release (routing + sprint lanes)

Two lanes carry every task — `sprint` (one process) and `team` (a process per step) —
so "is this release better" is really six questions, and each fails differently. Run
them in the order below: the cheap ones can reject a release before the paid ones run.

`scripts/run-sprint-benchmark.py` has seven modes. The comparable ones (`routing`,
`release`, `reliability`, `journey`) all diff two saved reports via `--compare`, and all
refuse to compare reports that declare different `format_version`, because a
silently-mismatched comparison is worse than none. The first three cut their own JSON
with `--out`; `journey` is compare-only — the live suite cuts its baselines (see step 4).

### 1. Router decisions — free, runs anywhere

```bash
uv run python scripts/run-sprint-benchmark.py routing --out /tmp/cand-route.json
```

0 model calls, no key, no store, no daemon — so this is the only mode that also runs
inside a worktree checked out at the previous release tag. Run it there first:

```bash
git worktree add /tmp/base-vX.Y.Z vX.Y.Z
(cd /tmp/base-vX.Y.Z && uv run python scripts/run-sprint-benchmark.py routing \
    --out /tmp/base-route.json)
uv run python scripts/run-sprint-benchmark.py routing \
    --compare /tmp/base-route.json /tmp/cand-route.json
git worktree remove /tmp/base-vX.Y.Z
```

Any row in the delta table is a task that would now run on a different lane, or be
refused for a different reason. That is a behaviour change users feel, so it belongs in
`CHANGELOG.md` whether it was intended or not.

### 2. Planned spend — free, deterministic

```bash
uv run python scripts/run-sprint-benchmark.py release --out /tmp/cand-release.json
uv run python scripts/run-sprint-benchmark.py release --compare /tmp/base-release.json \
    /tmp/cand-release.json
```

Every brief is measured at both effort tiers (`medium` and `low`); `high` is excluded
because it runs exactly as `medium` and would only pad the table. Watch `searches`,
`revise_rounds`, and `model_role` — a changed `model_role` means the tier now picks a
different model, which moves cost without touching any threshold.

### 3. What the fleet actually paid — reads the live store

```bash
uv run python scripts/run-sprint-benchmark.py tasks                       # per-lane table
uv run python scripts/run-sprint-benchmark.py tasks --baseline <id> --candidate <id>
```

Read-only over rows the runtime already wrote — safe to run at any time, and the
numbers are the ones the CEO experienced rather than a simulation. The per-lane table
carries the three miss rates worth a release's attention: `dead_end` (sprint picked for
work sprint could not finish), `downgrade` (the heuristic over-called team and the
safety net caught it), `upgrade` (a dead end someone paid a second time to redo).
Tasks with no route record are counted as lane `unknown`, never guessed at.

### 4. Delivery quality — spends money, judges blind

```bash
OPENROUTER_API_KEY=... uv run python scripts/run-sprint-benchmark.py judge \
    --baseline-dir base-out/ --candidate-dir cand-out/ --votes 3
```

Every other mode counts calls, searches, and dollars; none of them can tell you a
cheaper release delivers worse work. The judge is blind (no version labels in the
prompt), shuffles the two answers per vote so a position-biased judge averages out, and
defaults to a model of a different family from the one that ran the tasks. Cases present
in only one directory are reported as skipped, never judged.

### 5. Intake stability — spends money, measures dispersion

```bash
OPENROUTER_API_KEY=... uv run python scripts/run-sprint-benchmark.py reliability \
    --k 5 --out /tmp/cand-reliability.json
uv run python scripts/run-sprint-benchmark.py reliability \
    --compare /tmp/base-reliability.json /tmp/cand-reliability.json
```

Every mode above runs each case ONCE, which rounds model noise into "the result": a
release that made intake flaky still passes them all as long as the sampled run happened
to be good. This mode runs each brief `k` times and reports the spread.

`pass_rate` means "share of runs that did NOT fall through to fail-open" — not "share of
correct answers". `sprint_intake` calls the model and, on any failure, silently returns a
minimal plan built from the CEO's brief verbatim. Nothing goes red; the plan just gets
worse. A release that moves a case from 5/5 to 2/5 is a real regression no other mode
sees. Watch `flake` (pass_rate strictly between 0 and 1) and `assignee_mode` — work
quietly reassigned to a different agent is a behaviour change even at an unchanged rate.

Both sides of a `--compare` must have used the same `k`; the mode refuses otherwise,
since pass_rates over different denominators are not comparable. Runs that *raised* are
reported separately from fail-open ones, so a provider outage never reads as a quality
regression.

### 6. Journey baselines — compare-only

```bash
uv run python scripts/run-sprint-benchmark.py journey \
    --compare bench/journey_baseline_0.15.0.json /tmp/cand-journey.json
```

There is no "run" half: journey numbers come from the live suite below, which owns the
fleet boot, the temp home, and the budget ceilings. To cut a new baseline, point the live
journeys at an output path:

```bash
MY_CREW_JOURNEY_BASELINE_OUT=bench/journey_baseline_X.Y.Z.json \
    uv run pytest tests/fullflow_live -q -m live -k journey
```

Unset, that variable writes nothing — an ordinary live run must never overwrite the
committed baseline, or "compare against baseline" quietly becomes "compare against
whatever ran last" and can never fail.

Journeys run through the real model, so no two runs match. Discrete axes
(`terminal_state`, lane set) compare exactly; continuous ones (`cost_usd`, `wall_s`,
`llm_calls`) compare against deliberately wide relative thresholds. The point is catching
a release that made a journey half again as expensive or that now dies in a different
state — not micro-variance. A table that is always red gets ignored, which is worse than
no table.

### Live full-flow suite

The routing/lifecycle behaviour above is also asserted end-to-end against the real model
in `tests/fullflow_live/`. These spend real money, so they are **opt-in**: `addopts` in
`pyproject.toml` deselects the `live` marker, and a plain `uv run pytest` never runs them
even on a machine with a key configured. Pass `-m live` to select them; without an API key
they skip cleanly on top of that.

```bash
uv run pytest tests/fullflow_live -q -m "live and not live_slow"   # quick subset
uv run pytest tests/fullflow_live -q -m live                       # full suite (~12 min)
```

The quick subset is the pre-release gate; the full suite is worth one run per release.
Cases assert on the stored route record rather than on model prose, which is what keeps
them stable across model nondeterminism. No case writes externally or runs a real shell:
the guarded-brief cases assert the routing decision and the DAG shape, then stop without
ever pumping a step.
