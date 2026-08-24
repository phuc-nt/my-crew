"""Comment-preserving profile.yaml patches for web-initiated config writes (v87 P2).

`profile_editor.save_profile_yaml`'s siblings (e.g. `set_profile_enabled`) go through
`yaml.safe_load` → mutate a plain dict → `yaml.safe_dump` — this REBUILDS the document
from scratch, which silently drops comments and any hand-written key the loader/dumper
doesn't round-trip (the same class of bug as `company.save_company` rebuilding from a
fixed dict and erasing hand-written keys — see the project memory on that incident).

This module is the one sanctioned web-write path for profile.yaml going forward: it
loads with `ruamel.yaml`'s round-trip loader (preserves comments, key order, and
quote/flow styles), applies a SHALLOW patch to a whitelisted set of top-level blocks,
and dumps back with the same round-trip representer. Nothing outside the patched
key(s) changes.

Scope (v87 P2): only `safety.dry_run` was whitelisted at first — the per-agent dry-run
toggle that phase shipped. Phase 4 (agent config forms) extends this two ways:
  - ROOT-level scalars/lists (`name`, `model`, `model_chain`) — these are NOT nested
    under a block, so `patch_profile_yaml` accepts a bare `_ROOT` pseudo-block whose
    leaves are whitelisted in `_ALLOWED_ROOT_KEYS` and written directly at `doc[key]`.
  - New nested blocks `budget` (`monthly_usd`) and `schedule` (a free `kind -> cron`
    mapping, validated by the caller with `croniter.is_valid` before it ever reaches
    this module — `_ALLOWED_BLOCKS["schedule"]` is intentionally absent from the fixed
    leaf-whitelist path; see `_validate_patch`/`patch_profile_yaml` for the special case).
The existing `{"safety": {"dry_run": ...}}` nested contract (and its test) is unchanged.

Note on the two REPLACE paths (`model_chain` list, `schedule` block): they overwrite the
whole node, so ruamel re-emits it in default style — a list-item's inline comment or a
value's input quoting on THAT node may not survive (values are byte-safe: ruamel re-quotes
crons that need it). This is expected for whole-node replace, not a round-trip bug —
sibling keys and their comments elsewhere in the file are untouched. Only the leaf-merge
paths (`safety`, `budget`, root scalars) are true minimal-diff writes.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from my_crew.config.settings import MY_CREW_HOME
from my_crew.runtime.agent_paths import _validate_agent_id

# Top-level block name -> set of leaf keys a caller may patch inside it. Any key not
# listed here is rejected up front, so a caller can never widen this module's blast
# radius by accident (e.g. patching `bindings` or `telegram` through this path).
# `schedule` is deliberately absent: it is a free `kind -> cron` mapping (no fixed leaf
# set), so it is validated/replaced as a WHOLE block by `_ROOT_LIKE_REPLACE_BLOCKS`
# below rather than merged leaf-by-leaf like `safety`/`budget`.
_ALLOWED_BLOCKS: dict[str, frozenset[str]] = {
    "safety": frozenset({"dry_run"}),
    "budget": frozenset({"monthly_usd"}),
    # `runtime` holds infra keys the web form must NOT touch (checkpointer/store/
    # postgres_dsn), so only the advisor toggle is listed — a leaf-merge keeps the
    # neighbours and their comments untouched.
    "runtime": frozenset({"advisor_enabled"}),
}

# Root-level scalar/list keys a caller may patch directly on the document (not nested
# under a block) — Phase 4's `name`/`model`/`model_chain`. Patch shape for these is the
# pseudo-block `{"_root": {"name": "...", ...}}` (see `patch_profile_yaml`).
_ALLOWED_ROOT_KEYS: frozenset[str] = frozenset({"name", "model", "model_chain"})

# Blocks that are replaced WHOLESALE (not leaf-merged) because they have no fixed leaf
# set — currently only `schedule` (kind -> cron mapping, any kind name is legal). The
# caller is responsible for validating each value before calling `patch_profile_yaml`
# (routes_agent_profile_settings.py cron-validates every value with `croniter.is_valid`).
# `role_models` joins it for the same reason: it is a free `role -> model` mapping, and
# a role the form no longer lists must actually DISAPPEAR — a leaf-merge would leave the
# old override in place and keep billing for it, which is the silent-cost failure
# `_d_role_models` exists to prevent one layer down.
_ROOT_LIKE_REPLACE_BLOCKS: frozenset[str] = frozenset({"schedule", "role_models"})

#: Pseudo-block key a caller uses to patch root-level scalars/lists (see `_ALLOWED_ROOT_KEYS`).
ROOT_BLOCK = "_root"


class ProfileNotFoundError(LookupError):
    """Raised when the agent id has no `profiles/<id>/profile.yaml` on disk."""


class DisallowedPatchKeyError(ValueError):
    """Raised when a patch targets a block/key outside `_ALLOWED_BLOCKS`."""


def _yaml() -> YAML:
    # round_trip preserves comments/anchors/quote-style; default_flow_style=False keeps
    # newly-created nested maps block-style (matches how profile.yaml is hand-written)
    # instead of ruamel's compact `{a: b}` flow style for a block it creates from scratch.
    y = YAML(typ="rt")
    y.default_flow_style = False
    y.preserve_quotes = True
    return y


def _profile_yaml_path(agent_id: str) -> Path:
    """`profiles/<agent_id>/profile.yaml`, or raise if the agent/profile doesn't exist.

    Reuses the same id-validation `loader.py` / `agent_data_dir` enforce (reject any id
    that could escape the `profiles/` jail) before ever touching the filesystem.
    """
    try:
        safe_id = _validate_agent_id(agent_id)
    except ValueError as exc:
        raise ProfileNotFoundError(str(exc)) from exc
    path = MY_CREW_HOME / "profiles" / safe_id / "profile.yaml"
    if not path.exists():
        raise ProfileNotFoundError(
            f"Profile {agent_id!r} not found: {path} is missing. "
            f"Expected a directory profiles/{agent_id}/ with a profile.yaml."
        )
    return path


def _validate_patch(patch: dict[str, dict[str, Any]]) -> None:
    for block, leaves in patch.items():
        if block == ROOT_BLOCK:
            if not isinstance(leaves, dict):
                raise DisallowedPatchKeyError(
                    f"patch[{ROOT_BLOCK!r}] must be a mapping of root keys, "
                    f"got {type(leaves).__name__}."
                )
            unknown = set(leaves) - _ALLOWED_ROOT_KEYS
            if unknown:
                raise DisallowedPatchKeyError(
                    f"profile_patch cannot write root key(s) {sorted(unknown)} — only "
                    f"{sorted(_ALLOWED_ROOT_KEYS)} are whitelisted at root."
                )
            continue
        if block in _ROOT_LIKE_REPLACE_BLOCKS:
            if not isinstance(leaves, dict):
                raise DisallowedPatchKeyError(
                    f"patch[{block!r}] must be a mapping, got {type(leaves).__name__}."
                )
            continue
        if block not in _ALLOWED_BLOCKS:
            raise DisallowedPatchKeyError(
                f"profile_patch cannot write block {block!r} — only "
                f"{sorted(_ALLOWED_BLOCKS)} | {sorted(_ROOT_LIKE_REPLACE_BLOCKS)} | "
                f"{ROOT_BLOCK!r} are whitelisted."
            )
        if not isinstance(leaves, dict):
            raise DisallowedPatchKeyError(
                f"patch[{block!r}] must be a mapping of leaf keys, got {type(leaves).__name__}."
            )
        unknown = set(leaves) - _ALLOWED_BLOCKS[block]
        if unknown:
            raise DisallowedPatchKeyError(
                f"profile_patch cannot write {block}.{sorted(unknown)} — only "
                f"{sorted(_ALLOWED_BLOCKS[block])} are whitelisted under {block!r}."
            )


def patch_profile_yaml(agent_id: str, patch: dict[str, dict[str, Any]]) -> None:
    """Apply a shallow, whitelisted patch to `profiles/<agent_id>/profile.yaml`.

    `patch` is `{block_name: {leaf_key: new_value, ...}, ...}` — e.g.
    `{"safety": {"dry_run": False}}`. Every block/leaf must be in `_ALLOWED_BLOCKS` or
    this raises `DisallowedPatchKeyError` BEFORE touching the file (validate-then-write,
    same posture as `profile_editor.save_profile_yaml`).

    Round-trips with ruamel.yaml: an absent block is created fresh (block-style, not
    flow); an existing block is mutated in place so its comments, sibling keys, and key
    order survive untouched. Writes atomically (temp file + os.replace) so a crash never
    leaves a half-written profile.yaml.

    Raises `ProfileNotFoundError` for an unknown/invalid agent id.
    """
    _validate_patch(patch)
    path = _profile_yaml_path(agent_id)
    yaml = _yaml()
    doc = yaml.load(path.read_text(encoding="utf-8"))
    if doc is None:
        doc = CommentedMap()
    if not isinstance(doc, dict):
        raise ValueError(
            f"profile.yaml for {agent_id!r} must be a mapping, got {type(doc).__name__}."
        )

    for block, leaves in patch.items():
        if block == ROOT_BLOCK:
            # Root-level scalars/lists (`name`, `model`, `model_chain`) — written
            # directly on `doc`. ruamel preserves each key's existing style/comment
            # when the key already exists; a new key is appended at the end (same
            # "create fresh" posture as an absent nested block below).
            for key, value in leaves.items():
                doc[key] = value
            continue
        if block in _ROOT_LIKE_REPLACE_BLOCKS:
            # Whole-block replace (e.g. `schedule`): the caller submits the FULL
            # mapping the form has, so this is not a leaf-merge — stale kinds the form
            # no longer lists must actually disappear, which a leaf-merge could never do.
            doc[block] = leaves if isinstance(leaves, CommentedMap) else CommentedMap(leaves)
            continue
        existing_block = doc.get(block)
        if not isinstance(existing_block, dict):
            # Block absent (or not a mapping, e.g. `safety: null`) — create it fresh.
            existing_block = CommentedMap()
            doc[block] = existing_block
        for key, value in leaves.items():
            existing_block[key] = value

    import io

    buf = io.StringIO()
    yaml.dump(doc, buf)
    new_text = buf.getvalue()

    # PID-suffix the temp name so two concurrent same-agent writers never share one
    # scratch file (FastAPI dispatches sync `def` routes on the anyio threadpool, so
    # PATCH profile-settings + POST safety can land together). Same atomic convention
    # as profile_editor.py / company.py / env_writer.py.
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)


def read_safety_dry_run_raw(agent_id: str) -> bool | None:
    """The RAW `safety.dry_run` key as currently written in profile.yaml, or None if
    absent (i.e. the agent defers to the fleet `DRY_RUN` env / P1 default).

    Cheap peek (ruamel round-trip load, no builders) — used by the safety route to show
    whether the toggle is an explicit per-agent override or inherited from the fleet.
    Distinct from the loader's SETTINGS.dry_run, which is the fully-resolved effective
    value (profile → env → default) the worker actually runs with.
    """
    path = _profile_yaml_path(agent_id)
    doc = _yaml().load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        return None
    safety = doc.get("safety")
    if not isinstance(safety, dict) or "dry_run" not in safety:
        return None
    return bool(safety["dry_run"])


def read_profile_settings_raw(agent_id: str) -> dict[str, Any]:
    """The RAW values Phase 4's config form edits, as currently written in
    profile.yaml — used by `GET /api/agents/{id}/profile-settings` to pre-fill the
    form. Absent keys come back as the loader's own "absent" shape (`None`/`[]`/`{}`),
    matching `loader_mapping.py`'s fallback semantics: an absent `model` defers to the
    fleet `OPENROUTER_MODEL` env, an absent `model_chain` means a single model, an
    absent `budget.monthly_usd` is surfaced as `None` (caller decides the display
    default), and an absent/null `schedule` is `{}` (no scheduled kinds).
    """
    path = _profile_yaml_path(agent_id)
    doc = _yaml().load(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        doc = {}
    budget = doc.get("budget")
    schedule = doc.get("schedule")
    model_chain = doc.get("model_chain")
    role_models = doc.get("role_models")
    runtime = doc.get("runtime")
    return {
        "name": doc.get("name"),
        "model": doc.get("model"),
        "model_chain": list(model_chain) if isinstance(model_chain, list) else [],
        "budget_monthly_usd": (
            budget.get("monthly_usd") if isinstance(budget, dict) else None
        ),
        "schedule": dict(schedule) if isinstance(schedule, dict) else {},
        # `{}` means "no per-role override" — every role runs the fleet chain. The env
        # form (`OPENROUTER_ROLE_MODELS`) is deliberately NOT merged in here: this is the
        # raw per-agent value the form writes back, and showing an inherited env value in
        # an editable field would make saving the form silently pin the fleet default
        # into this agent's yaml.
        "role_models": {str(k): str(v) for k, v in role_models.items()}
        if isinstance(role_models, dict)
        else {},
        # `None` = key absent = inherit `ADVISOR_ENABLED` / the OFF default, which the
        # form renders differently from an explicit `false`.
        "advisor_enabled": (
            bool(runtime["advisor_enabled"])
            if isinstance(runtime, dict) and "advisor_enabled" in runtime
            else None
        ),
    }
