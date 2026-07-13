"""Create-agent + pack-listing logic for the web wizard (v3 M7).

`list_packs()` reads each `domain-packs/<x>-pack/pack.yaml` manifest (cheap YAML read —
no pack module import, so one broken pack cannot 500 the wizard's domain picker).

`create_agent(spec)` is the web sibling of `mpm agent register`, sharing the SAME
scaffold + registry-append primitives (`runtime/registry_edit`). The wizard sends more
than the CLI (name/domain/reports/schedule/bindings/persona), so the profile.yaml is
built from the default template DICT with those fields applied, then validated by the
SAME builders `load_profile` runs (bad spec ⇒ ValidationError, nothing written), then
scaffolded + registered. Registry failure rolls the profile dir back — no partial agent.

Secrets NEVER pass through here: bindings hold ids/keys/channels only; tokens stay in
`.env` (the wizard shows a copy-paste .env template instead — M7 security decision).
"""

from __future__ import annotations

import logging
import shutil

import yaml
from croniter import croniter

from src.packs.registry import discover_domains, pack_dir
from src.profile.loader import _PROFILES_DIR
from src.runtime.agent_paths import _validate_agent_id, agent_data_dir
from src.runtime.registry import _REGISTRY_PATH, load_registry
from src.runtime.registry_edit import append_registry, scaffold_profile_dir

logger = logging.getLogger(__name__)


class ValidationError(ValueError):
    """Bad create spec (→ 400). Message is user-facing."""


class ConflictError(RuntimeError):
    """Agent id already exists in profiles/ or registry (→ 409)."""


#: Binding keys the wizard may set, per server block in profile.yaml. Anything else in
#: the spec's bindings is rejected — the wizard must not write arbitrary profile keys.
_BINDING_KEYS: dict[str, tuple[str, ...]] = {
    "jira": ("project_key",),
    "confluence": ("space_key", "space_id", "okr_page_id"),
    "github": ("repo",),
    "slack": ("report_channel", "stakeholder_channel", "external_channels"),
}


def list_packs() -> list[dict]:
    """[{id, name, report_kinds, servers}] for every pack on disk (from pack.yaml)."""
    packs: list[dict] = []
    for domain in discover_domains():
        manifest = pack_dir(domain) / "pack.yaml"
        try:
            doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            logger.warning("skipping pack %r in /api/packs: bad pack.yaml", domain, exc_info=True)
            continue
        if not isinstance(doc, dict):  # a list/scalar manifest must not 500 the picker
            logger.warning("skipping pack %r in /api/packs: pack.yaml is not a mapping", domain)
            continue
        packs.append(
            {
                "id": str(doc.get("id") or domain),
                "name": str(doc.get("name") or domain),
                "report_kinds": [str(k) for k in (doc.get("report_kinds") or [])],
                "servers": [str(s) for s in (doc.get("servers") or [])],
            }
        )
    return packs


def create_agent(spec: dict, *, registry_path=None, profiles_dir=None) -> dict:
    """Validate the wizard spec → scaffold profiles/<id>/ → append registry. Atomic-ish:
    registry failure removes the just-created profile dir (no partial agent)."""
    reg = registry_path if registry_path is not None else _REGISTRY_PATH
    pdir = profiles_dir if profiles_dir is not None else _PROFILES_DIR

    agent_id, doc, soul_md = _build_profile_doc(spec, pdir)

    # Collision checks — BOTH targets before any write (mirrors `mpm agent register`).
    if (pdir / agent_id).exists():
        raise ConflictError(f"profiles/{agent_id}/ already exists.")
    if any(e.id == agent_id for e in load_registry(reg)):
        raise ConflictError(f"{agent_id!r} is already in the registry.")

    profile_text = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
    try:
        scaffold_profile_dir(pdir, agent_id, profile_yaml_text=profile_text, soul_md=soul_md)
    except FileExistsError:  # lost the check→mkdir race with a concurrent create
        raise ConflictError(f"profiles/{agent_id}/ already exists.") from None
    try:
        append_registry(reg, agent_id, enabled=doc["enabled"])
    except Exception:
        shutil.rmtree(pdir / agent_id, ignore_errors=True)  # rollback: no orphan profile
        raise
    return {"id": agent_id, "domain": doc["domain"], "reports": doc["reports"]}


def _build_profile_doc(spec: dict, profiles_dir) -> tuple[str, dict, str | None]:
    """Spec → (agent_id, validated profile.yaml dict, SOUL.md text or None).

    Raises ValidationError with a user-facing message on any bad field. Validation runs
    the REAL config builders (same as profile_editor) so a profile the wizard writes is
    a profile `load_profile` accepts — no file is written before this passes.
    """
    try:
        agent_id = _validate_agent_id(str(spec.get("id") or ""))
    except ValueError as exc:
        raise ValidationError(str(exc)) from None
    if agent_id == "ceo":
        # v33 P4: "ceo" is the virtual consult-propose target that routes a question
        # to the human operator — a REAL agent under this id would shadow colleague
        # consults into the clarify path. Reserved at the create door only (read
        # paths must keep working even for hypothetical legacy data).
        raise ValidationError("mã 'ceo' là mã dành riêng (kênh hỏi CEO) — chọn mã khác")

    domain = str(spec.get("domain") or "pm").strip() or "pm"
    known = discover_domains()
    if domain not in known:
        raise ValidationError(f"unknown domain {domain!r} (installed: {', '.join(known)})")

    pack_kinds = _pack_report_kinds(domain)
    # reports MAY be empty — a staffer whose work comes from assigned team tasks rather
    # than a scheduled worker --report run has no report kind of its own. Only VALIDATE
    # the kinds that ARE given.
    reports = [str(k) for k in (spec.get("reports") or [])]
    bad_kinds = [k for k in reports if k not in pack_kinds]
    if bad_kinds:
        raise ValidationError(
            f"report kind(s) {bad_kinds} not served by the {domain!r} pack "
            f"(valid: {sorted(pack_kinds)})"
        )

    schedule_raw = spec.get("schedule") or {}
    if not isinstance(schedule_raw, dict):
        raise ValidationError("schedule must be a mapping of report kind → cron string")
    schedule: dict[str, str] = {}
    for kind, cron in schedule_raw.items():
        if str(kind) not in reports:
            raise ValidationError(f"schedule for {kind!r} but it is not a selected report kind")
        if not croniter.is_valid(str(cron)):
            raise ValidationError(f"invalid cron string for {kind!r}: {cron!r}")
        schedule[str(kind)] = str(cron)

    template = (profiles_dir / "default" / "profile.yaml").read_text(encoding="utf-8")
    doc = yaml.safe_load(template)
    doc["name"] = str(spec.get("name") or agent_id)
    # v32: the one-click template/crew path creates DISABLED (plan invariant — tokens
    # first, then the operator enables); the wizard keeps its historical enabled-True.
    # Only the literal False flips it, so a spec can't smuggle other values through.
    doc["enabled"] = spec.get("enabled") is not False
    doc["domain"] = domain
    doc["reports"] = reports
    doc["schedule"] = schedule
    # Opt-in web-search flag (loader default false). Only ever written as a literal True
    # so a spec can't smuggle arbitrary values into profile.yaml through this key.
    if spec.get("web_search"):
        doc["web_search"] = True
    # v32: opt-in OpenAlex academic search — same literal-True-only posture.
    if spec.get("academic_search"):
        doc["academic_search"] = True
    # v30: optional trust mode. Only the two literal policies pass through; absent ⇒ the
    # profile inherits the global default (TRUST_MODE env / builder default "autonomous").
    trust_mode = str(spec.get("trust_mode") or "").strip().lower()
    if trust_mode:
        if trust_mode not in ("autonomous", "guarded"):
            raise ValidationError("trust_mode must be 'autonomous' or 'guarded'")
        safety = doc.setdefault("safety", {})
        safety["trust_mode"] = trust_mode
    # v20.5: opt-in agent runtime backend. Either a bare kind string (native/create_agent) or a
    # mapping {kind, sandbox: {...}} (deep_agent needs a sandbox block). The loader validates
    # either shape (parse_agent_runtime_config accepts both); an unknown kind → RuntimeError at
    # load, caught by the create flow's builder run below. A deep_agent written as a bare string
    # would be DOA (its required sandbox block missing), so the mapping form must pass through.
    runtime = spec.get("agent_runtime")
    if isinstance(runtime, dict) and runtime.get("kind"):
        doc["agent_runtime"] = runtime
    elif isinstance(runtime, str):
        runtime_kind = runtime.strip()
        if runtime_kind and runtime_kind != "native":
            doc["agent_runtime"] = runtime_kind
    # v36 P2: the role template this agent came from (one-click template path). Written
    # as a clean single-segment string only — the loader turns it into a live skills
    # source. A path-y value can't smuggle a traversal: it names a dir under templates/.
    template_role = str(spec.get("template_role") or "").strip()
    if template_role:
        if "/" in template_role or "\\" in template_role or template_role in (".", ".."):
            raise ValidationError(f"template_role {template_role!r} không hợp lệ")
        doc["template_role"] = template_role
        # v36 P3: the config version + snapshot applied at create (upgrade baseline).
        # Only recorded alongside a valid template_role, and only as plain data.
        version = spec.get("template_version")
        if isinstance(version, int):
            doc["template_version"] = version
        applied = spec.get("template_config_applied")
        if isinstance(applied, dict):
            doc["template_config_applied"] = applied
    _apply_bindings(doc, spec.get("bindings") or {})

    # Run the real builders — the exact validation `load_profile` applies (incl. the
    # stakeholder-channel cross-check). Raises before anything is written.
    from src.config.config_builders import (
        build_reporting_config_from_dict,
        build_settings_from_dict,
    )
    from src.profile.loader_mapping import build_reporting_dict, build_settings_dict

    try:
        build_settings_from_dict(build_settings_dict(doc, agent_data_dir(agent_id)))
        build_reporting_config_from_dict(build_reporting_dict(doc))
    except (ValueError, RuntimeError) as exc:
        raise ValidationError(str(exc)) from None

    soul_md = str(spec.get("persona") or "") or None
    return agent_id, doc, soul_md


def _apply_bindings(doc: dict, bindings: dict) -> None:
    """Merge wizard bindings into the template's bindings block — whitelisted keys only."""
    if not isinstance(bindings, dict):
        raise ValidationError("bindings must be a mapping")
    target = doc.setdefault("bindings", {})
    for server, values in bindings.items():
        allowed = _BINDING_KEYS.get(str(server))
        if allowed is None:
            raise ValidationError(f"unknown bindings server {server!r}")
        if not isinstance(values, dict):
            raise ValidationError(f"bindings.{server} must be a mapping")
        block = target.setdefault(str(server), {})
        for key, value in values.items():
            if key not in allowed:
                raise ValidationError(f"bindings.{server}.{key} is not settable here")
            if key == "external_channels":
                if not isinstance(value, list):
                    raise ValidationError("bindings.slack.external_channels must be a list")
                block[key] = [str(v) for v in value]
            else:
                block[key] = str(value)


def _pack_report_kinds(domain: str) -> frozenset[str]:
    """The kinds a pack's manifest declares (cheap pack.yaml read, no module import)."""
    manifest = pack_dir(domain) / "pack.yaml"
    try:
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValidationError(f"pack {domain!r} has no readable pack.yaml: {exc}") from None
    if not isinstance(doc, dict):
        raise ValidationError(f"pack {domain!r} pack.yaml is not a mapping")
    return frozenset(str(k) for k in (doc.get("report_kinds") or []))
