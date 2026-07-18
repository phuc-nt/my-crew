"""Per-agent knowledge + skills form for Agent Studio (v7 M18b). Session-auth-gated.

SOUL/PROJECT are edited as a small FORM instead of raw markdown — the form fields round-trip
through marker-wrapped markdown (my_crew/agent/knowledge_template). A file hand-edited past the
markers surfaces as raw_mode and is served/saved raw, never silently overwritten by the form.

The skills picker reads the domain's skill catalog + the `skills:` list in profile.yaml, and
writes the selection back (only catalog names accepted).
"""

from __future__ import annotations

import yaml
from fastapi import Body, HTTPException

from my_crew.server.routes_agent_studio_shared import _AGENT_ID_RE, router

_DOC_FILE = {"soul": "SOUL.md", "project": "PROJECT.md"}


def _require_agent(agent_id: str) -> None:
    """404 if the agent has no profile.yaml — so the knowledge routes never materialize a
    partial profile dir for an arbitrary (regex-valid) id (review M1). Mirrors the skills
    routes, which 404 via load_profile."""
    from my_crew.profile.loader import _PROFILES_DIR

    if not (_PROFILES_DIR / agent_id / "profile.yaml").exists():
        raise HTTPException(status_code=404, detail=f"không tìm thấy agent {agent_id!r}")


@router.get("/{agent_id}/knowledge/{doc}")
def get_knowledge(agent_id: str, doc: str) -> dict:
    """Read SOUL/PROJECT as FORM FIELDS (parsed from markers) — or raw_mode when the file was
    hand-edited past the markers (M18b two-way form)."""
    if not _AGENT_ID_RE.match(agent_id) or doc not in _DOC_FILE:
        raise HTTPException(status_code=400, detail="tham số không hợp lệ")
    _require_agent(agent_id)
    from my_crew.agent.knowledge_template import parse
    from my_crew.server import profile_editor

    text = profile_editor.read_profile_files(agent_id).get(doc, "")
    parsed = parse(doc, text)
    return {"doc": doc, "raw_mode": parsed.raw_mode, "fields": parsed.fields, "raw": parsed.raw}


@router.put("/{agent_id}/knowledge/{doc}")
def put_knowledge(agent_id: str, doc: str, fields: dict | None = Body(default=None, embed=True),  # noqa: B008
                  raw: str | None = Body(default=None, embed=True)) -> dict:
    """Write SOUL/PROJECT. If `raw` is given (advanced editor), save it verbatim; otherwise
    render the form `fields` into marker markdown. Atomic via profile_editor.save_markdown.

    Guards (review C1/H1/H2): a PUT must carry `raw` OR `fields` (empty → 400, no blank
    overwrite). The form path re-parses the CURRENT file and REFUSES (409) if it's raw_mode —
    the "is this file form-representable?" check lives server-side, not only in the UI, so a
    stale tab or a direct caller can't clobber hand-written prose. render() itself rejects
    marker-injected values (round-trip corruption) → 400."""
    if not _AGENT_ID_RE.match(agent_id) or doc not in _DOC_FILE:
        raise HTTPException(status_code=400, detail="tham số không hợp lệ")
    _require_agent(agent_id)
    if raw is None and fields is None:
        raise HTTPException(status_code=400, detail="cần 'raw' hoặc 'fields'")
    from my_crew.agent.knowledge_template import FIELD_KEYS, MarkerInValueError, parse, render
    from my_crew.server import profile_editor

    if raw is not None:
        text = raw
    else:
        # An empty/keyless `fields` dict almost always means a stale or buggy client — NOT an
        # intentional "blank everything". Rendering it would wipe a populated file to empty
        # markers (H2). A genuine empty form still submits every known key (with "" values),
        # so require at least one recognized field key before we touch the file.
        if not (set(fields) & FIELD_KEYS[doc]):
            raise HTTPException(status_code=400, detail="thiếu trường biểu mẫu")
        # Form path: don't overwrite a file the form can't represent (H1 — server-side guard).
        current = profile_editor.read_profile_files(agent_id).get(doc, "")
        if parse(doc, current).raw_mode:
            raise HTTPException(
                status_code=409,
                detail="File đang ở chế độ nâng cao (đã sửa tay). Lưu bằng chế độ raw để không "
                       "ghi đè nội dung viết tay.",
            )
        try:
            text = render(doc, {str(k): str(v) for k, v in fields.items()})
        except MarkerInValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    profile_editor.save_markdown(agent_id, _DOC_FILE[doc], text)
    return {"ok": True}


@router.get("/{agent_id}/skills")
def get_skills(agent_id: str) -> dict:
    """The skill catalog for this agent's domain + which are currently selected in its
    profile (M18b skills picker). Selected = the `skills:` list in profile.yaml."""
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.skills.skill_loader import load_skills

    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        raise HTTPException(status_code=404, detail=f"không tìm thấy agent {agent_id!r}") from None
    catalog = load_skills(domain=loaded.domain)
    selected = set(loaded.skills)
    return {"skills": [{"name": s.name, "description": s.description,
                        "selected": s.name in selected} for s in catalog]}


@router.put("/{agent_id}/skills")
def put_skills(agent_id: str, names: list[str] = Body(..., embed=True)) -> dict:  # noqa: B008
    """Set the agent's selected skills (writes the `skills:` list to profile.yaml). Only names
    in the domain catalog are accepted — an unknown skill is rejected, not silently written."""
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    from my_crew.profile.loader import load_profile
    from my_crew.runtime.agent_paths import agent_data_dir
    from my_crew.server import profile_editor
    from my_crew.skills.skill_loader import load_skills

    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        raise HTTPException(status_code=404, detail=f"không tìm thấy agent {agent_id!r}") from None
    valid = {s.name for s in load_skills(domain=loaded.domain)}
    chosen = [n for n in names if n in valid]
    unknown = [n for n in names if n not in valid]
    if unknown:
        raise HTTPException(status_code=400, detail=f"skill không có: {', '.join(unknown)}")

    text = profile_editor.read_profile_files(agent_id).get("profile", "")
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict):
        raise HTTPException(status_code=500, detail="profile.yaml hỏng")
    doc["skills"] = chosen
    try:
        profile_editor.save_profile_yaml(agent_id, yaml.safe_dump(doc, sort_keys=False,
                                                                  allow_unicode=True))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"lưu profile lỗi: {exc}") from None
    return {"ok": True, "skills": chosen}
