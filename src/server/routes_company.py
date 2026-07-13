"""Company identity + staff-template routes.

Config-only writes (company.yaml + reading profiles/templates/) — like
`routes_agents_admin.py`, these never touch the Action Gateway. Both routers live under
the `/api` prefix, which is NOT in `auth._PUBLIC_PREFIXES`, so the existing AuthMiddleware
already protects them the same way it protects every other `/api/*` route — no new auth
wiring needed, just don't add these paths to the public allowlist.

Templates prefill the wizard AND (v32) are directly executable: `GET /api/staff-templates` lists
`profiles/templates/<role>/template.yaml` + `SOUL.md`; creating an agent from a template
still goes through `agent_create.create_agent` — both the wizard's `POST /api/agents/create`
and the v32 one-click `POST /api/agents/create-from-template` / `POST /api/crew/create`
(spec built SERVER-side from the template; the client sends only role_id)
(no new write path, no gateway involvement).
"""

from __future__ import annotations

import logging

import yaml
from fastapi import APIRouter, Body, HTTPException

from src.config.settings import REPO_ROOT
from src.runtime.company import load_company, save_company
from src.runtime.registry import load_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["company"])

_TEMPLATES_DIR = REPO_ROOT / "profiles" / "templates"

#: template.yaml v1 contract — see profiles/templates/*/template.yaml docstring for why
#: `skills` is deliberately excluded.
_TEMPLATE_FIELDS = ("role", "domain", "reports", "bindings_hint", "recommended_runtime")


@router.get("/company")
def get_company() -> dict:
    """Company identity for the dashboard header / Setup wizard (no secrets)."""
    c = load_company()
    return {
        "name": c.name,
        "coordinator_id": c.coordinator_id,
        "team_task_cap_usd": c.team_task_cap_usd,
        "team_task_concurrency": c.team_task_concurrency,
        "team_task_auto_confirm": c.team_task_auto_confirm,
    }


@router.post("/company")
def post_company(
    name: str = Body(..., embed=True),
    coordinator_id: str | None = Body(None, embed=True),
    team_task_cap_usd: float | None = Body(None, embed=True),
    team_task_auto_confirm: bool | None = Body(None, embed=True),
) -> dict:
    """Set company name + coordinator (config-only write, mirrors registry mutation).

    `coordinator_id`, when set, MUST already exist in `registry.yaml` — the wizard must
    not let the CEO point the company at a nonexistent agent.

    Load-modify-save (red-team F7): fields this request does NOT carry are re-written
    from the CURRENT company.yaml, never silently reset to defaults — the old behavior
    dropped `team_task_concurrency` back to 2 on every save.
    """
    if not isinstance(name, str):
        raise HTTPException(status_code=400, detail="name phải là chuỗi")
    coord = coordinator_id.strip() if isinstance(coordinator_id, str) else None
    coord = coord or None
    if coord is not None:
        known_ids = {e.id for e in load_registry()}
        if coord not in known_ids:
            raise HTTPException(
                status_code=400, detail=f"coordinator_id {coord!r} không có trong registry"
            )
    if team_task_cap_usd is not None and team_task_cap_usd <= 0:
        raise HTTPException(status_code=400, detail="team_task_cap_usd phải > 0")

    current = load_company()
    # Omitted fields preserve the current value (F7 + review M2 — a Setup-wizard save
    # that carries no cap must not reset the CEO's configured cap back to 2.0).
    cap = current.team_task_cap_usd if team_task_cap_usd is None else float(team_task_cap_usd)
    auto_confirm = (
        current.team_task_auto_confirm if team_task_auto_confirm is None
        else bool(team_task_auto_confirm)
    )
    save_company(
        name.strip(), coord, cap,
        team_task_concurrency=current.team_task_concurrency,
        team_task_auto_confirm=auto_confirm,
    )
    return {
        "name": name.strip(),
        "coordinator_id": coord,
        "team_task_cap_usd": cap,
        "team_task_concurrency": current.team_task_concurrency,
        "team_task_auto_confirm": auto_confirm,
    }


@router.get("/staff-templates")
def get_staff_templates() -> dict:
    """[{role_id, role, domain, reports, bindings_hint, persona}] for the wizard's picker.

    Reads `profiles/templates/<role_id>/template.yaml` (+ SOUL.md for persona prefill).
    A broken template dir is skipped (logged), never 500s the picker — same posture as
    `agent_create.list_packs()` skipping a broken pack.yaml.
    """
    return {"templates": _load_templates()}


def _load_templates() -> list[dict]:
    if not _TEMPLATES_DIR.is_dir():
        return []
    templates: list[dict] = []
    for role_dir in sorted(_TEMPLATES_DIR.iterdir()):
        if not role_dir.is_dir():
            continue
        template = _load_one_template(role_dir)
        if template is not None:
            templates.append(template)
    return templates


def _load_one_template(role_dir) -> dict | None:
    manifest = role_dir / "template.yaml"
    try:
        doc = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        logger.warning(
            "skipping staff template %r: bad template.yaml", role_dir.name, exc_info=True
        )
        return None
    if not isinstance(doc, dict):
        logger.warning("skipping staff template %r: template.yaml is not a mapping", role_dir.name)
        return None

    soul_path = role_dir / "SOUL.md"
    persona = ""
    if soul_path.is_file():
        try:
            persona = soul_path.read_text(encoding="utf-8")
        except OSError:
            # A SOUL.md that exists but can't be read (permissions, TOCTOU removal, bad
            # encoding) must not 500 the whole picker — skip just the persona prefill,
            # same "skip this one, keep the rest" posture as a bad template.yaml above.
            logger.warning(
                "staff template %r: SOUL.md unreadable, persona left blank", role_dir.name,
                exc_info=True,
            )

    return {
        "role_id": role_dir.name,
        "role": str(doc.get("role") or role_dir.name),
        "domain": str(doc.get("domain") or ""),
        "reports": [str(k) for k in (doc.get("reports") or [])],
        "bindings_hint": [str(b) for b in (doc.get("bindings_hint") or [])],
        "persona": persona,
        # Opt-in web-search flag the wizard forwards into the created profile (only the
        # nghien-cuu template ships true; absent ⇒ false, matching the profile default).
        "web_search": bool(doc.get("web_search", False)),
        # v20.5: which runtime backend this role is best served by (wizard prefill; user can
        # override). Absent ⇒ "native" (the safe default).
        "recommended_runtime": str(doc.get("recommended_runtime") or "native"),
        # v32 one-click contract additions (all optional; absent keeps v1 behavior):
        # academic_search mirrors web_search; schedule is {report kind: cron} defaults
        # (validated by create_agent against the role's reports); has_skills tells the
        # FE card a skills/ folder will be copied into the created agent.
        "academic_search": bool(doc.get("academic_search", False)),
        "schedule": {str(k): str(v) for k, v in (doc.get("schedule") or {}).items()}
        if isinstance(doc.get("schedule"), dict) else {},
        "has_skills": (role_dir / "skills").is_dir(),
        # v36 P3: config version — an agent records the version it was created with so a
        # later template bump surfaces an upgrade badge. Absent ⇒ 1 (the baseline).
        "version": int(doc.get("version") or 1),
    }

@router.post("/agents/create-from-template")
def create_agent_from_template(
    role_id: str = Body(..., embed=True),
    agent_id: str | None = Body(None, embed=True),
) -> dict:
    """One-click create: server-side spec from the template → the SAME create_agent
    door the wizard uses. The client cannot send profile config through here."""
    from src.server import template_create
    from src.server.agent_create import ConflictError, ValidationError

    try:
        return template_create.create_from_template(role_id, agent_id)
    except template_create.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


@router.get("/crew/preview")
def get_crew_preview() -> dict:
    """Confirm-dialog payload for "Tạo cả đội": members + exists flags + coordinator plan."""
    from src.server import template_create

    try:
        return template_create.crew_preview()
    except template_create.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/crew/create")
def post_crew_create() -> dict:
    """Create the default crew (per-member independent; existing members skipped)."""
    from src.server import template_create

    try:
        return template_create.create_crew()
    except template_create.TemplateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.get("/agents/template-status")
def get_template_status() -> dict:
    """v36 P3: per-agent template config version + whether a newer template exists.
    Drives the Team-page "template có bản mới" badge."""
    from src.server import template_upgrade

    return {"agents": template_upgrade.agent_upgrade_status()}


@router.get("/agents/{agent_id}/template-upgrade")
def preview_template_upgrade(agent_id: str) -> dict:
    """Preview which config fields an upgrade would apply vs keep (user-customized)."""
    from src.server import template_upgrade

    try:
        return template_upgrade.preview_upgrade(agent_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.post("/agents/{agent_id}/template-upgrade")
def apply_template_upgrade(agent_id: str) -> dict:
    """Apply the config upgrade (backup first; user-customized fields kept). A template
    whose config fails validation is rejected by the save door (RuntimeError → 400) AFTER
    the backup was written, so the live profile is never left half-written."""
    from src.server import template_upgrade

    try:
        return template_upgrade.apply_upgrade(agent_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
