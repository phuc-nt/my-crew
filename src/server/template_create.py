"""One-click create from a staff template + whole-crew bootstrap (v32 P2).

The wizard's templates were prefill-only; this module makes them EXECUTABLE while
keeping the single validated door: the spec is built SERVER-SIDE from the template
files (the client sends only `role_id` + an optional id override — it cannot smuggle
arbitrary profile config), then goes through the SAME `agent_create.create_agent` the
wizard and ops-chat use. After a successful create, the template's `skills/` folder
(if any) is copied into the new agent's per-agent skills dir — regular .md files only,
no symlink following (the template dir is repo data; the copy must not be able to pull
anything from outside it).

Crew bootstrap reads `profiles/templates/crew.yaml` (ONE default crew — CEO decision
v32) and creates each member independently: an existing member is SKIPPED (reported,
never an abort) so re-running is idempotent and a partial failure leaves the created
members standing. The crew's coordinator is wired into `company.yaml::coordinator_id`
only when no coordinator is configured yet — an explicit CEO choice is never clobbered.
"""

from __future__ import annotations

import logging

import yaml

from src.server import agent_create
from src.server.routes_company import _TEMPLATES_DIR, _load_one_template

logger = logging.getLogger(__name__)

_CREW_MANIFEST = _TEMPLATES_DIR / "crew.yaml"


class TemplateError(ValueError):
    """Unknown/broken template or crew manifest (→ 400). Message is user-facing."""


def create_from_template(role_id: str, agent_id: str | None = None) -> dict:
    """Create one agent from `profiles/templates/<role_id>/`. Raises TemplateError /
    agent_create.ValidationError / agent_create.ConflictError (routes map them)."""
    template = _load_template_or_raise(role_id)
    final_id = (agent_id or role_id).strip().lower()
    spec = _spec_from_template(template, final_id)
    created = agent_create.create_agent(spec)
    _copy_template_skills(role_id, created["id"])
    return {
        **created,
        "name": template["role"],
        "hint": "Agent đang TẮT: điền token vào .env (nếu vai cần) rồi bật ở trang Đội.",
    }


def create_crew() -> dict:
    """Create every crew member (independent, skip-existing) + wire the coordinator.

    Returns {crew, created, skipped, failed, coordinator_id} — `skipped` are members
    whose agent id already exists (idempotent re-run), `failed` carry the per-member
    error message (one broken member never aborts the rest).
    """
    manifest = _load_crew_manifest()
    from src.runtime.registry import load_registry

    existing = {e.id for e in load_registry()}
    created: list[str] = []
    skipped: list[str] = []
    failed: list[dict] = []
    for role_id in manifest["members"]:
        if role_id in existing:
            skipped.append(role_id)
            continue
        try:
            create_from_template(role_id)
            created.append(role_id)
        except (TemplateError, agent_create.ValidationError,
                agent_create.ConflictError) as exc:
            failed.append({"role_id": role_id, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — one member must not abort the crew
            logger.exception("crew create: member %r failed", role_id)
            failed.append({"role_id": role_id, "error": f"lỗi không mong đợi: {exc}"})

    coordinator_id = _wire_coordinator(manifest.get("coordinator") or "",
                                       created + skipped)
    return {
        "crew": manifest.get("name") or "crew",
        "created": created, "skipped": skipped, "failed": failed,
        "coordinator_id": coordinator_id,
    }


def crew_preview() -> dict:
    """The confirm-dialog payload: members + which already exist + coordinator plan.

    Read-only; the SAME manifest/registry reads `create_crew` uses, so the preview and
    the create can never disagree on membership.
    """
    manifest = _load_crew_manifest()
    from src.runtime.company import load_company
    from src.runtime.registry import load_registry

    existing = {e.id for e in load_registry()}
    members = []
    for role_id in manifest["members"]:
        template = _load_one_template(_TEMPLATES_DIR / role_id) or {}
        members.append({
            "role_id": role_id,
            "role": template.get("role") or role_id,
            "domain": template.get("domain") or "",
            "exists": role_id in existing,
        })
    current = load_company().coordinator_id
    return {
        "crew": manifest.get("name") or "crew",
        "members": members,
        "coordinator": manifest.get("coordinator") or "",
        "coordinator_already_set": bool(current),
        "current_coordinator": current,
    }


def _load_template_or_raise(role_id: str) -> dict:
    # The role_id doubles as the created agent id (same charset rule); validating it
    # here also confines the template path to one segment under templates/.
    from src.runtime.agent_paths import _validate_agent_id

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


def _spec_from_template(template: dict, agent_id: str) -> dict:
    """Template → create_agent spec. Every field passes the SAME validation the wizard
    hits — this function only selects, never invents config."""
    spec: dict = {
        "id": agent_id,
        "name": template["role"],
        "domain": template["domain"],
        "reports": template["reports"],
        "bindings": {},
        # Plan invariant (v32): one-click creates land DISABLED — .env tokens first,
        # then one click on the Team page turns the agent on.
        "enabled": False,
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


def _copy_template_skills(role_id: str, agent_id: str) -> None:
    """Copy the template's skills/ into the new agent's per-agent skills dir.

    Best-effort AFTER a successful create (a skill-copy hiccup must not roll back the
    agent). Only regular files under the template dir are copied — `resolve()` guards
    against a symlink pointing outside the templates tree.
    """
    src_dir = (_TEMPLATES_DIR / role_id / "skills")
    if not src_dir.is_dir():
        return
    from src.packs.registry import profile_skills_dir

    # Same profiles root create_agent just wrote to (module attr — tests repoint it).
    dest = profile_skills_dir(agent_id, profiles_dir=agent_create._PROFILES_DIR)
    try:
        root = _TEMPLATES_DIR.resolve()
        for path in sorted(src_dir.rglob("*.md")):
            resolved = path.resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                continue
            rel = path.relative_to(src_dir)
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(resolved.read_bytes())
    except OSError:
        logger.warning("template %r: skills copy to %r failed", role_id, agent_id,
                       exc_info=True)


def _wire_coordinator(coordinator_role: str, available: list[str]) -> str | None:
    """Point company.yaml at the crew's coordinator — only when none is set yet."""
    from src.runtime.company import load_company, save_company

    company = load_company()
    if company.coordinator_id:
        return company.coordinator_id  # explicit CEO choice — never clobbered
    if not coordinator_role or coordinator_role not in available:
        return None
    # Domain guard: a pre-existing agent that merely SHARES the coordinator's id must
    # actually be the coordinator role's domain before company.yaml points at it.
    try:
        from src.profile.loader import load_profile
        from src.runtime.agent_paths import agent_data_dir

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
    )
    return coordinator_role


def _load_crew_manifest() -> dict:
    if not _CREW_MANIFEST.is_file():
        raise TemplateError("chưa có profiles/templates/crew.yaml — không có crew mẫu")
    try:
        doc = yaml.safe_load(_CREW_MANIFEST.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise TemplateError(f"crew.yaml không đọc được: {exc}") from None
    members = doc.get("members")
    if not isinstance(doc, dict) or not isinstance(members, list) or not members:
        raise TemplateError("crew.yaml phải có danh sách members")
    return {
        "name": str(doc.get("name") or "crew"),
        "coordinator": str(doc.get("coordinator") or ""),
        "members": [str(m) for m in members],
    }
