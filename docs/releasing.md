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

1. Ensure main is green (CI: BE pytest + ruff + FE vitest/tsc/build).
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

```bash
python -m venv /tmp/v && /tmp/v/bin/pip install my-crew
MY_CREW_HOME=/tmp/crew-home /tmp/v/bin/my-crew agent list   # seeds + bootstraps
MY_CREW_HOME=/tmp/crew-home /tmp/v/bin/my-crew serve --web-only  # /health → 200
```
