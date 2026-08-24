"""Structured agent config forms for Agent Studio (v88 P4). Session-auth-gated.

Before this phase, the config keys operators touch most (display name, model +
model_chain, budget monthly cap, schedule, band) were only editable via the raw YAML
editor on the Advanced tab (`routes_ops_json.py`) or the CLI. This module adds
structured, validated write surfaces so those edits are ≤3 clicks and never risk a
hand-typo breaking YAML shape:

  - `GET/PATCH /api/agents/{id}/profile-settings` — name/model/model_chain/budget cap/
    schedule, all written through `profile_patch` (ruamel round-trip, comment-preserving —
    see that module's docstring for why this is the one sanctioned web-write path).
  - `GET/POST /api/agents/{id}/band` — the autonomy band (supervised/normal/trusted). This
    is NOT a profile.yaml key: it is a separate SQLite side-effect (`BandStore.get`/`.set`),
    the POST making the exact same call the chat-ops `set_band` command makes
    (`ops_catalog.py:_run_set_band`) — same args, same audit columns (reason/changed_by/
    updated_at). No profile write, no chat-ops slot-parser involved. GET exists so the
    header dropdown can show the real current value instead of a blind default.
  - `GET /api/agents/model-catalog` — model ids to populate the model dropdown, read from
    `config/model_prices.yaml` (never hardcoded, never fetched from OpenRouter — that table
    is an operator-maintained price list, not a live catalog, but its keys ARE valid model
    ids the fleet already prices, which is a reasonable "known-good" suggestion list; the
    FE still allows free-text for any id outside it, since OpenRouter adds models constantly).

Cross-process staleness: same posture as `routes_agent_safety.py` — a profile-settings
write does not need a restart signal, because both the scheduler tick loop and each
spawned worker subprocess re-read `profile.yaml` fresh on every dispatch (no in-process
cache). A band write also needs no restart: `BandStore.get` is read fresh wherever the
band is consulted (`review_insert.py`).
"""

from __future__ import annotations

from typing import Any

from croniter import croniter
from fastapi import Body, HTTPException

from my_crew.server import profile_patch
from my_crew.server.routes_agent_studio_shared import _AGENT_ID_RE, router

_VALID_BANDS = ("supervised", "normal", "trusted")


def _require_agent(agent_id: str) -> None:
    """404 if the agent has no profile.yaml (mirrors routes_agent_safety.py)."""
    from my_crew.profile.loader import _PROFILES_DIR

    if not (_PROFILES_DIR / agent_id / "profile.yaml").exists():
        raise HTTPException(status_code=404, detail=f"không tìm thấy agent {agent_id!r}")


@router.get("/{agent_id}/profile-settings")
def get_agent_profile_settings(agent_id: str) -> dict:
    """Current raw values for the config form (pre-fill), straight from profile.yaml.

    These are the RAW written values, not the loader's fully-resolved effective ones
    (e.g. `model` absent here means "follow the fleet OPENROUTER_MODEL env", which the
    FE renders via the "Bỏ trống = dùng model chung của công ty" help text rather than
    re-deriving the fleet value itself).
    """
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    _require_agent(agent_id)
    values = profile_patch.read_profile_settings_raw(agent_id)
    return {"agent_id": agent_id, **values}


def _validate_model_chain(model_chain: Any) -> list[str]:
    if not isinstance(model_chain, list) or not all(
        isinstance(m, str) and m.strip() for m in model_chain
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "model_chain phải là danh sách chuỗi model id không rỗng "
                "(danh sách rỗng vẫn hợp lệ)"
            ),
        )
    return model_chain


def _validate_budget(budget_monthly_usd: Any) -> float:
    if isinstance(budget_monthly_usd, bool) or not isinstance(budget_monthly_usd, int | float):
        raise HTTPException(status_code=400, detail="budget_monthly_usd phải là số")
    value = float(budget_monthly_usd)
    if value < 0:
        raise HTTPException(status_code=400, detail="budget_monthly_usd phải >= 0")
    return value


def _validate_schedule(schedule: Any) -> dict[str, str]:
    if not isinstance(schedule, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in schedule.items()
    ):
        raise HTTPException(
            status_code=400, detail="schedule phải là object dạng {loại_báo_cáo: cron}"
        )
    for kind, cron in schedule.items():
        if not croniter.is_valid(cron):
            raise HTTPException(
                status_code=400, detail=f"schedule[{kind!r}] không phải cron hợp lệ: {cron!r}"
            )
    return schedule


def _validate_role_models(role_models: Any) -> dict[str, str]:
    """Reject anything `_d_role_models` would reject, with ITS message verbatim.

    Reusing the loader's own validator is the point: a role name the form accepts but
    the loader rejects would write a profile.yaml that fails at the next dispatch —
    an error the operator sees as a dead agent, far from the form that caused it.
    Model ids stay free-text (same trust level as hand-editing the yaml); only the
    ROLE names are a closed set.
    """
    if not isinstance(role_models, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in role_models.items()
    ):
        raise HTTPException(
            status_code=400, detail="role_models phải là object dạng {vai_trò: model_id}"
        )
    from my_crew.config.config_builders import _d_role_models

    try:
        _d_role_models(role_models)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return role_models


@router.patch("/{agent_id}/profile-settings")
def patch_agent_profile_settings(
    agent_id: str,
    name: str | None = Body(default=None),
    model: str | None = Body(default=None),
    model_chain: list[str] | None = Body(default=None),  # noqa: B008
    budget_monthly_usd: float | None = Body(default=None),
    schedule: dict[str, str] | None = Body(default=None),  # noqa: B008
    role_models: dict[str, str] | None = Body(default=None),  # noqa: B008
    advisor_enabled: bool | None = Body(default=None),
) -> dict:
    """Whitelisted subset write: any of `name`/`model`/`model_chain`/
    `budget_monthly_usd`/`schedule`/`role_models`/`advisor_enabled`, all optional — only
    the keys present in the body are patched. Each value is validated BEFORE any file
    write (validate-then-write, same posture as `profile_patch` itself); an invalid
    value 400s and touches nothing.

    `model_chain: []` is a legal, meaningful value (⇒ single model, no fallback chain) —
    it is distinguished from "field omitted" by FastAPI's own None-default handling, so a
    caller who wants to CLEAR the chain sends `model_chain: []`, not by leaving it out.
    """
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    _require_agent(agent_id)

    root_patch: dict[str, Any] = {}
    if name is not None:
        if not name.strip():
            raise HTTPException(status_code=400, detail="name không được rỗng")
        root_patch["name"] = name
    if model is not None:
        # Empty string clears the per-agent override (⇒ follow the fleet model) — a
        # deliberate, valid value, not rejected. Format is loosely `vendor/name` but
        # OpenRouter adds ids constantly, so this is documentary only, never enforced.
        root_patch["model"] = model
    if model_chain is not None:
        root_patch["model_chain"] = _validate_model_chain(model_chain)

    patch: dict[str, dict[str, Any]] = {}
    if root_patch:
        patch[profile_patch.ROOT_BLOCK] = root_patch
    if budget_monthly_usd is not None:
        patch["budget"] = {"monthly_usd": _validate_budget(budget_monthly_usd)}
    if schedule is not None:
        patch["schedule"] = _validate_schedule(schedule)
    if role_models is not None:
        # Whole-mapping replace (`_ROOT_LIKE_REPLACE_BLOCKS`), so `{}` is how the form
        # clears every per-role override and returns the agent to the fleet chain.
        patch["role_models"] = _validate_role_models(role_models)
    if advisor_enabled is not None:
        patch["runtime"] = {"advisor_enabled": advisor_enabled}

    if patch:
        try:
            profile_patch.patch_profile_yaml(agent_id, patch)
        except profile_patch.ProfileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"không tìm thấy agent {agent_id!r}"
            ) from None
        except profile_patch.DisallowedPatchKeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    return {"agent_id": agent_id, "needs_restart": False}


@router.get("/{agent_id}/band")
def get_agent_band(agent_id: str) -> dict:
    """Current band (defaults to `normal` when never set — `BandStore.get`'s own fail
    direction). Needed so the header dropdown shows the REAL current value instead of
    guessing/defaulting blind — a control that always renders "normal" regardless of the
    stored value would be actively misleading, not just incomplete.
    """
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    _require_agent(agent_id)

    from my_crew.runtime.band_store import BandStore

    store = BandStore()
    try:
        band = store.get(agent_id)
    finally:
        store.close()
    return {"agent_id": agent_id, "band": band}


@router.post("/{agent_id}/band")
def set_agent_band(
    agent_id: str,
    band: str = Body(...),
    reason: str = Body(default="CEO đặt tay"),
) -> dict:
    """Set the agent's autonomy band — the SAME call chat-ops `set_band` makes
    (`ops_catalog.py:_run_set_band`): `BandStore().set(agent_id, band, reason=...,
    changed_by="ceo")`. Not a profile.yaml write; a separate SQLite side-effect table
    (`agent_bands`), so this route calls `BandStore` directly rather than routing
    through the chat-ops slot parser (there is no slot-parsing need — the body is
    already structured).
    """
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    _require_agent(agent_id)

    from my_crew.runtime.band_store import BandStore

    store = BandStore()
    try:
        store.set(agent_id, band, reason=reason, changed_by="ceo")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    finally:
        store.close()
    return {"agent_id": agent_id, "band": band}


@router.get("/model-catalog")
def get_model_catalog() -> dict:
    """Model ids known to `config/model_prices.yaml`, sorted — populates the model
    dropdown's suggestion list. The FE still allows free-text for any id outside this
    catalog (OpenRouter adds models constantly; this table is an operator-maintained
    price list, not a live catalog). An empty/missing file yields `{"models": []}`
    (never a 500 — the dropdown degrades to free-text-only).
    """
    from my_crew.llm.model_pricing import load_prices

    return {"models": sorted(load_prices())}
