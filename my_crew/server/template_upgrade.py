"""Template CONFIG version-pin + upgrade (v36 P3).

Skills load live from the template (P2); the template's CONFIG (reports, schedule,
tool flags, recommended runtime) is still applied once at create. This module lets a
role template bump its `version` and an operator upgrade an agent's config WITH REVIEW:

- A template carries `version: <int>`. An agent created from it records `template_role`,
  `template_version`, and `template_config_applied` (the exact config snapshot applied).
- `agent_upgrade_status()` lists agents whose template has a newer version.
- `preview_upgrade(agent_id)` diffs the current template snapshot against the agent's
  `template_config_applied` baseline and the agent's live profile, classifying each field:
    * apply    — template changed AND the agent still has the old template value
                 (user never customized it) → safe to re-apply.
    * keep     — the agent's live value differs from its baseline (user customized) →
                 left untouched, only reported.
    * unchanged— template value equals the baseline.
- `apply_upgrade(agent_id)` writes the "apply" fields into profile.yaml through the same
  validate-then-atomic-write door the editor uses, AFTER backing up the full profile.yaml
  to `profile.yaml.bak-<ts>` (user-data is never overwritten blind).

An agent with no `template_role` (wizard/pre-v36) is out of scope — never shown, never
touched. An agent missing `template_config_applied` (created before P3) treats every
field as user-customized (safest: apply nothing, just report the version gap).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Config fields a template may drive + upgrade. `domain` is deliberately NOT here — a
#: domain change would re-validate reports/bindings and is not a safe auto-apply; it stays
#: a create-time-only choice.
_CONFIG_FIELDS = ("reports", "schedule", "web_search", "academic_search", "recommended_runtime")


def config_snapshot(template: dict) -> dict:
    """The upgradeable config a template applies, normalized. This is BOTH the baseline
    stored at create and the comparison target at upgrade — one definition, no drift."""
    return {
        "reports": list(template.get("reports") or []),
        "schedule": dict(template.get("schedule") or {}),
        "web_search": bool(template.get("web_search")),
        "academic_search": bool(template.get("academic_search")),
        "recommended_runtime": str(template.get("recommended_runtime") or "native"),
    }


def _agent_live_value(doc: dict, field: str):
    """The agent's current value for a config field, read from its profile.yaml doc, in
    the SAME normalized shape `config_snapshot` produces (so equality is meaningful)."""
    if field == "reports":
        return list(doc.get("reports") or [])
    if field == "schedule":
        return dict(doc.get("schedule") or {})
    if field in ("web_search", "academic_search"):
        return bool(doc.get(field))
    if field == "recommended_runtime":
        rt = doc.get("agent_runtime")
        if isinstance(rt, dict):
            return str(rt.get("kind") or "native")
        return str(rt or "native")
    return None


def _load_template(role_id: str) -> dict | None:
    from my_crew.server.routes_company import _TEMPLATES_DIR, _load_one_template

    return _load_one_template(_TEMPLATES_DIR / role_id)


def agent_upgrade_status() -> list[dict]:
    """One row per template-bound agent: {agent_id, role, applied_version, latest_version,
    upgradable}. `upgradable` is True when latest > applied. Pre-v36 agents (no
    template_role) are omitted."""
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.registry import load_registry

    rows: list[dict] = []
    for entry in load_registry():
        try:
            loaded = load_profile(entry.id)
        except Exception:  # noqa: BLE001 — one broken profile must not hide the rest
            logger.warning("upgrade-status: load %r failed (skipped)", entry.id, exc_info=True)
            continue
        role = getattr(loaded, "template_role", None)
        if not role:
            continue
        template = _load_template(role)
        if not template:
            continue
        latest = int(template.get("version") or 1)
        applied = _applied_version(entry.id)
        rows.append({
            "agent_id": entry.id,
            "role": role,
            "applied_version": applied,
            "latest_version": latest,
            "upgradable": latest > applied,
        })
    return rows


def _read_profile_doc(agent_id: str) -> dict:
    import yaml

    from my_crew.server.profile_editor import _profile_dir

    text = (_profile_dir(agent_id) / "profile.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text) or {}


def _applied_version(agent_id: str) -> int:
    return int(_read_profile_doc(agent_id).get("template_version") or 1)


def preview_upgrade(agent_id: str) -> dict:
    """Classify each config field for an upgrade. Returns {role, applied_version,
    latest_version, apply: {field: new_value}, keep: [field], unchanged: [field]}.

    Raises ValueError if the agent is not template-bound."""
    doc = _read_profile_doc(agent_id)
    role = doc.get("template_role")
    if not role:
        raise ValueError(f"agent {agent_id!r} không gắn template (không thể nâng cấp)")
    template = _load_template(str(role))
    if not template:
        raise ValueError(f"template {role!r} không đọc được")

    latest_snapshot = config_snapshot(template)
    baseline = doc.get("template_config_applied") or {}
    has_baseline = bool(baseline)

    apply: dict = {}
    keep: list[str] = []
    unchanged: list[str] = []
    for field in _CONFIG_FIELDS:
        new_val = latest_snapshot[field]
        base_val = baseline.get(field)
        live_val = _agent_live_value(doc, field)
        if new_val == base_val:
            unchanged.append(field)
            continue
        # Template changed this field. Re-apply ONLY if the agent still holds the old
        # template value (user never customized). No baseline ⇒ can't prove that ⇒ keep.
        if has_baseline and live_val == base_val:
            apply[field] = new_val
        else:
            keep.append(field)
    return {
        "role": role,
        "applied_version": int(doc.get("template_version") or 1),
        "latest_version": int(template.get("version") or 1),
        "apply": apply,
        "keep": keep,
        "unchanged": unchanged,
    }


def apply_upgrade(agent_id: str) -> dict:
    """Apply the previewed 'apply' fields to profile.yaml (backup first). Returns the same
    shape as `preview_upgrade` plus `backup` (the backup filename). No-op-safe: if nothing
    is applicable, the version is still advanced and no fields change."""
    import time

    import yaml

    from my_crew.server.profile_editor import _atomic_write, _profile_dir, save_profile_yaml

    plan = preview_upgrade(agent_id)
    doc = _read_profile_doc(agent_id)
    template = _load_template(str(plan["role"]))

    # Backup the FULL current profile.yaml before any write (user-data, never blind).
    profile_path = _profile_dir(agent_id) / "profile.yaml"
    # time.time() is process-local wall clock; fine for a unique-enough backup suffix.
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time()))
    backup_name = f"profile.yaml.bak-{stamp}"
    _atomic_write(profile_path.with_name(backup_name),
                  profile_path.read_text(encoding="utf-8"))

    # Merge the apply-fields, refresh the baseline + version, then write through the
    # validate-then-atomic door (a template value that fails validation raises, no write).
    for field, value in plan["apply"].items():
        _write_field(doc, field, value)
    doc["template_version"] = int(template.get("version") or 1)
    doc["template_config_applied"] = config_snapshot(template)
    save_profile_yaml(agent_id, yaml.safe_dump(doc, allow_unicode=True, sort_keys=False))
    return {**plan, "backup": backup_name}


def _write_field(doc: dict, field: str, value) -> None:
    """Write one upgraded config field back into the profile doc in its native shape."""
    if field == "recommended_runtime":
        if value == "native":
            doc.pop("agent_runtime", None)
        elif value == "deep_agent":
            doc["agent_runtime"] = {"kind": "deep_agent", "sandbox": {"provider": "docker"}}
        else:
            doc["agent_runtime"] = value
    else:
        doc[field] = value
