"""Per-agent dry-run visibility + toggle for Agent Studio (v87 P2). Session-auth-gated.

The shipped `profiles/default/profile.yaml` writes `dry_run: true` explicitly, and every
templated hire clones it verbatim — combined with the loader rule "a present profile key
beats the fleet `DRY_RUN` env" (`loader_mapping.py:89`), a `.env` DRY_RUN=false is silently
ignored per-agent. This route makes the EFFECTIVE value visible (the exact value
`load_profile` resolves, i.e. what the worker actually runs with) and lets the operator
flip the per-agent override from the web without opening YAML.

Cross-process staleness: `my-crew serve` runs the web (this route) and the
scheduler/worker (`my_crew.runtime.service`) as SEPARATE OS processes (`serve_cmd.py`).
A profile write here does NOT need a restart signal, because BOTH dispatch paths re-read
`profile.yaml` fresh on every run — no in-process caching:
  - the service tick loop calls `load_profile(entry.id)` fresh on every dispatch before
    it decides what's due (`runtime/service.py::run_tick`, load_profile at :299/:331/:398);
  - each spawned worker subprocess (`python -m my_crew.runtime.worker`) ALSO calls
    `load_profile(agent_id, ...)` fresh at the top of `main()` (`runtime/worker.py:174`);
  - `load_profile` itself does a plain `yaml_path.read_text()` per call — no module-level
    cache to go stale.
So a flip here is effective on the agent's NEXT scheduled tick / triggered run, not
"instantly mid-run" (a run already in flight keeps the settings it started with) and
never requires a service restart — unlike the `.env`-key writes in `routes_connections.py`
(env vars ARE process-boot-cached via `load_dotenv`, hence THAT route's `needs_restart`).
"""

from __future__ import annotations

from fastapi import Body, HTTPException

from my_crew.server import profile_patch
from my_crew.server.routes_agent_studio_shared import _AGENT_ID_RE, router


def _require_agent(agent_id: str) -> None:
    """404 if the agent has no profile.yaml (mirrors routes_agent_knowledge.py)."""
    from my_crew.profile.loader import _PROFILES_DIR

    if not (_PROFILES_DIR / agent_id / "profile.yaml").exists():
        raise HTTPException(status_code=404, detail=f"không tìm thấy agent {agent_id!r}")


@router.get("/{agent_id}/safety")
def get_agent_safety(agent_id: str) -> dict:
    """Effective dry-run for this agent: the SAME resolution the worker uses
    (profile.yaml `safety.dry_run` -> fleet `DRY_RUN` env -> default True).

    `dry_run` is the effective value; `dry_run_source` says whether it comes from an
    explicit per-agent override or is inherited from the fleet env/default, so the UI
    can explain "why is this on" without re-deriving the loader's 3-tier rule.
    """
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    _require_agent(agent_id)

    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir

    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=f"hồ sơ lỗi: {str(exc)[:160]}") from None

    raw = profile_patch.read_safety_dry_run_raw(agent_id)
    return {
        "agent_id": agent_id,
        "dry_run": bool(loaded.settings.dry_run),
        "dry_run_source": "profile" if raw is not None else "fleet",
    }


@router.patch("/{agent_id}/safety")
def patch_agent_safety(agent_id: str, dry_run: bool = Body(..., embed=True)) -> dict:
    """Set this agent's `safety.dry_run` override in profile.yaml (comment-preserving
    write via `profile_patch`). Effective on the agent's next scheduled tick / triggered
    run — both dispatch paths re-read profile.yaml fresh, so no restart is required
    (see module docstring for the verified evidence).
    """
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    try:
        profile_patch.patch_profile_yaml(agent_id, {"safety": {"dry_run": dry_run}})
    except profile_patch.ProfileNotFoundError:
        raise HTTPException(status_code=404, detail=f"không tìm thấy agent {agent_id!r}") from None
    return {"agent_id": agent_id, "dry_run": dry_run, "needs_restart": False}
