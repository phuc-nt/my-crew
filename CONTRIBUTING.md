# Contributing

## Dev setup

```bash
git clone git@github.com:phuc-nt/my-crew.git && cd my-crew
uv sync --extra deep        # deep = optional Docker-sandbox tier (needs Docker to run, not to test)
uv run pytest -q            # 2360+ BE tests — no secrets, no network, no Docker required
uv run ruff check .
cd web && npm install && npm test   # 201 FE tests
```

A git checkout keeps all user state repo-local (`.env`, `registry.yaml`,
`profiles/`, `.data/`) — `MY_CREW_HOME` docs: see the deployment guide.

## Rules of the road

- **The test suite must stay secret-free.** Any test that needs a real key,
  network, or Docker daemon gets a `skipif` gate. CI runs the whole suite on
  clean runners.
- **The Action Gateway is the invariant.** Changes that add a write path must
  route it through the gateway; changes to Lớp A/Lớp B semantics need an
  explicit maintainer decision, not a drive-by refactor.
- **Conventional commits** (`feat:`, `fix:`, `refactor:` …), no AI references.
- Python: ruff-clean, snake_case, type hints on public functions; line length 100.
- FE: TypeScript strict; build for real (`npm run build`) when the dist matters —
  the served bundle at `my_crew/server/static/app/` is committed.
- Docs: user-facing behavior changes update `docs/`; development narrative goes
  to `docs/journals/`.

## Releases

Maintainer-driven; see [docs/releasing.md](docs/releasing.md).
