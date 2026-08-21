"""One-click create from a staff template + whole-crew bootstrap (v32 P2).

The wizard's templates were prefill-only; this module makes them EXECUTABLE while
keeping the single validated door: the spec is built SERVER-SIDE from the template
files (the client sends only `role_id` + an optional id override — it cannot smuggle
arbitrary profile config), then goes through the SAME `agent_create.create_agent` the
wizard and ops-chat use. The created agent records `template_role` (v36 P2), so its
skills load LIVE from `profiles/templates/<role>/skills/` at runtime — no copy — and a
template skill edit reaches every agent of that role with no re-scaffold. It also records
`template_version` + a config baseline (v36 P3) so a later template bump surfaces a
config-upgrade with review (see `template_upgrade.py`).

Crew bootstrap reads `profiles/templates/crews/<crew_id>.yaml` and creates each member
independently: an existing member is SKIPPED (reported, never an abort) so re-running is
idempotent and a partial failure leaves the created members standing. The crew's
coordinator is wired into `company.yaml::coordinator_id` only when no coordinator is
configured yet — an explicit CEO choice is never clobbered.

v32 shipped ONE crew (`crew.yaml`); the personal crew is the second real use case, so the
manifest moved into `crews/` with `office` as the default (callers that pass no crew id —
`mpm crew init`, pre-v71 web clients — still get the office crew, byte-identically). A
member may be a bare role id or `{role, id}`; the latter lets a crew ADOPT an existing
agent under its own id instead of creating a second one for the same job.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from my_crew.server import agent_create
from my_crew.server.routes_company import _TEMPLATES_DIR, _load_one_template

logger = logging.getLogger(__name__)

_CREWS_DIR = _TEMPLATES_DIR / "crews"
#: Pre-v71 single-manifest location. Read only when `crews/<id>.yaml` is absent, so an
#: install that customized the old file in place keeps working until it migrates.
_LEGACY_CREW_MANIFEST = _TEMPLATES_DIR / "crew.yaml"
DEFAULT_CREW_ID = "office"


class TemplateError(ValueError):
    """Unknown/broken template or crew manifest (→ 400). Message is user-facing."""


def create_from_template(role_id: str, agent_id: str | None = None) -> dict:
    """Create one agent from `profiles/templates/<role_id>/`. Raises TemplateError /
    agent_create.ValidationError / agent_create.ConflictError (routes map them)."""
    template = _load_template_or_raise(role_id)
    final_id = (agent_id or role_id).strip().lower()
    spec = _spec_from_template(template, final_id, role_id)
    created = agent_create.create_agent(spec)
    # v36 P2: skills are NOT copied — they load live from the template dir via the
    # agent's `template_role` (see load_skill_pool). Editing a template skill now reaches
    # every agent of this role with no re-scaffold.
    return {
        **created,
        "name": template["role"],
        # Minimal bilingual: this codebase's other first-run HTTPException strings are
        # Vietnamese-only (routes_office_assign.py:76,81 / routes_outputs.py:150 /
        # ops_autopilot.py:79-91) — no new BE i18n mechanism for 2 strings, just add the
        # English line inline for this exact hint (success criterion scope).
        "hint": "Agent đang TẮT: điền token vào .env (nếu vai cần) rồi bật ở trang Đội. "
                "(Agent is OFF: fill in the token in .env if the role needs one, "
                "then enable it on the Team page.)",
    }


def create_crew(crew_id: str = DEFAULT_CREW_ID) -> dict:
    """Create every crew member (independent, skip-existing) + wire the coordinator.

    Returns {crew, created, skipped, failed, coordinator_id} — `skipped` are members
    whose agent id already exists (idempotent re-run), `failed` carry the per-member
    error message (one broken member never aborts the rest).
    """
    manifest = _load_crew_manifest(crew_id)
    from my_crew.runtime.registry import load_registry

    existing = {e.id for e in load_registry()}
    created: list[str] = []
    skipped: list[str] = []
    failed: list[dict] = []
    for member in manifest["members"]:
        role_id, agent_id = member["role"], member["id"]
        # Skip on the AGENT id, not the role: an adopting member (`{role, id}`) exists
        # under its own id, and its role template may never have been instantiated.
        #
        # A skipped agent keeps whatever `template_role` its own profile already has —
        # we do NOT stamp the manifest's role onto a profile someone wrote by hand. That
        # would silently rewrite user data to claim a template link the operator never
        # made, and template_upgrade would then start offering to overwrite a hand-tuned
        # agent. The cost of not stamping: an adopted agent loads no skills from
        # `profiles/templates/<role>/skills/` and stays out of upgrade scope.
        if agent_id in existing:
            skipped.append(agent_id)
            continue
        try:
            create_from_template(role_id, agent_id)
            created.append(agent_id)
        except (TemplateError, agent_create.ValidationError,
                agent_create.ConflictError) as exc:
            failed.append({"role_id": agent_id, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — one member must not abort the crew
            logger.exception("crew create: member %r failed", agent_id)
            failed.append({"role_id": agent_id, "error": f"lỗi không mong đợi: {exc}"})

    coordinator_id = _wire_coordinator(manifest.get("coordinator") or "",
                                       created + skipped)
    return {
        "crew": manifest.get("name") or "crew",
        "crew_id": crew_id,
        "created": created, "skipped": skipped, "failed": failed,
        "coordinator_id": coordinator_id,
    }


def list_crews() -> list[dict]:
    """Available crew manifests for the UI picker — [{id, name, member_count}].

    Sorted with the default crew first, then alphabetically, so the picker's first
    option is the one a caller who sends no crew id would get.
    """
    crews: list[dict] = []
    for path in sorted(_CREWS_DIR.glob("*.yaml")) if _CREWS_DIR.is_dir() else []:
        try:
            manifest = _load_crew_manifest(path.stem)
        except TemplateError:
            logger.warning("crew list: manifest %s unreadable — skipped", path.name)
            continue
        crews.append({
            "id": path.stem,
            "name": manifest["name"],
            "member_count": len(manifest["members"]),
        })
    if not crews and _LEGACY_CREW_MANIFEST.is_file():
        manifest = _load_crew_manifest(DEFAULT_CREW_ID)
        crews.append({"id": DEFAULT_CREW_ID, "name": manifest["name"],
                      "member_count": len(manifest["members"])})
    crews.sort(key=lambda c: (c["id"] != DEFAULT_CREW_ID, c["id"]))
    return crews


def crew_preview(crew_id: str = DEFAULT_CREW_ID) -> dict:
    """The confirm-dialog payload: members + which already exist + coordinator plan.

    Read-only; the SAME manifest/registry reads `create_crew` uses, so the preview and
    the create can never disagree on membership.
    """
    manifest = _load_crew_manifest(crew_id)
    from my_crew.runtime.company import load_company
    from my_crew.runtime.registry import load_registry

    existing = {e.id for e in load_registry()}
    members = []
    for member in manifest["members"]:
        role_id, agent_id = member["role"], member["id"]
        template = _load_one_template(_TEMPLATES_DIR / role_id) or {}
        members.append({
            # `role_id` stays the agent id the create will use — the key the existing
            # dialog renders and matches against `created`/`skipped`.
            "role_id": agent_id,
            "role": template.get("role") or role_id,
            "domain": template.get("domain") or "",
            "exists": agent_id in existing,
        })
    current = load_company().coordinator_id
    return {
        "crew": manifest.get("name") or "crew",
        "crew_id": crew_id,
        "members": members,
        "coordinator": manifest.get("coordinator") or "",
        "coordinator_already_set": bool(current),
        "current_coordinator": current,
    }


def _load_template_or_raise(role_id: str) -> dict:
    # The role_id doubles as the created agent id (same charset rule); validating it
    # here also confines the template path to one segment under templates/.
    from my_crew.runtime.agent_paths import _validate_agent_id

    try:
        _validate_agent_id(role_id)
    except ValueError as exc:
        raise TemplateError(str(exc)) from None
    role_dir = _TEMPLATES_DIR / role_id
    if not role_dir.is_dir():
        raise TemplateError(f"không có template {role_id!r}")
    template = _load_one_template(role_dir)
    if template is None:
        raise TemplateError(f"template {role_id!r} hỏng (template.yaml không đọc được)")
    return template


def _template_config_snapshot(template: dict) -> dict:
    # Local import avoids an import cycle (template_upgrade imports routes_company, which
    # imports template_create). The snapshot definition lives in one place.
    from my_crew.server.template_upgrade import config_snapshot

    return config_snapshot(template)


def _spec_from_template(template: dict, agent_id: str, role_id: str) -> dict:
    """Template → create_agent spec. Every field passes the SAME validation the wizard
    hits — this function only selects, never invents config. `role_id` is the template
    dir name, recorded as `template_role` so skills load live from it (v36 P2)."""
    spec: dict = {
        "id": agent_id,
        "name": template["role"],
        "domain": template["domain"],
        "reports": template["reports"],
        "bindings": {},
        # Plan invariant (v32): one-click creates land DISABLED — .env tokens first,
        # then one click on the Team page turns the agent on.
        "enabled": False,
        # v36 P2: bind the agent to its role template so skills load LIVE from the
        # template dir at runtime (no copy) — a template skill edit reaches this agent.
        "template_role": role_id,
        # v36 P3: record the template's config version + the exact config snapshot applied
        # at create, so a later config-upgrade can tell "user never touched this field"
        # (safe to re-apply) from "user customized it" (keep, just report).
        "template_version": int(template.get("version") or 1),
        "template_config_applied": _template_config_snapshot(template),
    }
    if template.get("schedule"):
        spec["schedule"] = template["schedule"]
    if template.get("persona"):
        spec["persona"] = template["persona"]
    if template.get("web_search"):
        spec["web_search"] = True
    if template.get("academic_search"):
        spec["academic_search"] = True
    runtime = template.get("recommended_runtime") or "native"
    if runtime != "native":
        # deep_agent needs its sandbox block to be loadable — the docker default the
        # wizard would pick; a bare string kind is enough for create_agent's mapping rule.
        spec["agent_runtime"] = (
            {"kind": "deep_agent", "sandbox": {"provider": "docker"}}
            if runtime == "deep_agent" else runtime
        )
    return spec


def _wire_coordinator(coordinator_role: str, available: list[str]) -> str | None:
    """Point company.yaml at the crew's coordinator — only when none is set yet."""
    from my_crew.runtime.company import load_company, save_company

    company = load_company()
    if company.coordinator_id:
        return company.coordinator_id  # explicit CEO choice — never clobbered
    if not coordinator_role or coordinator_role not in available:
        return None
    # Domain guard: a pre-existing agent that merely SHARES the coordinator's id must
    # actually be the coordinator role's domain before company.yaml points at it.
    try:
        from my_crew.profile.loader import load_profile
        from my_crew.runtime.agent_paths import agent_data_dir

        actual = load_profile(coordinator_role, data_dir=agent_data_dir(coordinator_role))
        expected = _load_one_template(_TEMPLATES_DIR / coordinator_role) or {}
        if expected.get("domain") and actual.domain != expected["domain"]:
            logger.warning(
                "crew coordinator %r has domain %r (template expects %r) — not wired",
                coordinator_role, actual.domain, expected.get("domain"),
            )
            return None
    except (FileNotFoundError, RuntimeError):
        return None
    save_company(
        company.name, coordinator_role,
        team_task_cap_usd=company.team_task_cap_usd,
        team_task_concurrency=company.team_task_concurrency,
        team_task_auto_confirm=company.team_task_auto_confirm,
        autopilot=company.autopilot,
    )
    return coordinator_role


def _crew_manifest_path(crew_id: str) -> Path:
    """Resolve `crews/<crew_id>.yaml`, falling back to the pre-v71 `crew.yaml` for the
    default crew only. The id is validated as ONE path segment before it touches the
    filesystem, so a crafted id can never read outside the crews dir."""
    if not crew_id or not crew_id.replace("-", "").replace("_", "").isalnum():
        raise TemplateError(f"tên crew không hợp lệ: {crew_id!r}")
    path = _CREWS_DIR / f"{crew_id}.yaml"
    if path.is_file():
        return path
    if crew_id == DEFAULT_CREW_ID and _LEGACY_CREW_MANIFEST.is_file():
        return _LEGACY_CREW_MANIFEST
    available = ", ".join(c["id"] for c in list_crews()) or "(không có crew nào)"
    raise TemplateError(f"không có crew {crew_id!r} — có: {available}")


def _load_crew_manifest(crew_id: str = DEFAULT_CREW_ID) -> dict:
    path = _crew_manifest_path(crew_id)
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise TemplateError(f"{path.name} không đọc được: {exc}") from None
    members = doc.get("members")
    if not isinstance(doc, dict) or not isinstance(members, list) or not members:
        raise TemplateError(f"{path.name} phải có danh sách members")
    return {
        "name": str(doc.get("name") or "crew"),
        "coordinator": str(doc.get("coordinator") or ""),
        "members": [_parse_member(m, path.name) for m in members],
    }


def _parse_member(member: object, manifest_name: str) -> dict:
    """One manifest member → {role, id}. A bare string is a role instantiated under its
    own name; `{role, id}` names the agent id explicitly, which is how a crew adopts an
    already-existing agent instead of creating a duplicate for the same job."""
    if isinstance(member, str):
        return {"role": member, "id": member}
    if isinstance(member, dict):
        role = str(member.get("role") or "").strip()
        agent_id = str(member.get("id") or role).strip()
        if role:
            return {"role": role, "id": agent_id}
    raise TemplateError(
        f"{manifest_name}: member phải là role id hoặc {{role, id}} — gặp {member!r}")
