"""Per-agent Company Docs opt-in for Agent Studio (v7 M19 S4). Session-auth-gated.

Mirrors the M18b skills picker: GET returns the whole library flagged with which docs THIS
agent opted into (its profile's `company_docs:` list); PUT writes the chosen slugs back to
profile.yaml. Only real library slugs are accepted — a slug not in the library is rejected,
never silently written.
"""

from __future__ import annotations

import yaml
from fastapi import Body, HTTPException

from src.company_docs import store
from src.server.routes_agent_studio_shared import _AGENT_ID_RE, router


def _require_agent(agent_id: str) -> None:
    from src.profile.loader import _PROFILES_DIR

    if not (_PROFILES_DIR / agent_id / "profile.yaml").exists():
        raise HTTPException(status_code=404, detail=f"không tìm thấy agent {agent_id!r}")


def _selected_slugs(agent_id: str) -> set[str]:
    from src.profile.loader import load_profile
    from src.runtime.agent_paths import agent_data_dir

    try:
        loaded = load_profile(agent_id, data_dir=agent_data_dir(agent_id))
    except (FileNotFoundError, RuntimeError):
        raise HTTPException(status_code=404, detail=f"không tìm thấy agent {agent_id!r}") from None
    return set(loaded.company_docs)


@router.get("/{agent_id}/company-docs")
def get_agent_company_docs(agent_id: str) -> dict:
    """The whole library + which docs this agent reads (selected = profile `company_docs:`)."""
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    _require_agent(agent_id)
    selected = _selected_slugs(agent_id)
    return {"docs": [{"slug": d.slug, "title": d.title, "selected": d.slug in selected}
                     for d in store.list_docs()]}


@router.put("/{agent_id}/company-docs")
def put_agent_company_docs(agent_id: str, slugs: list[str] = Body(..., embed=True)) -> dict:  # noqa: B008
    """Set which docs this agent reads (writes `company_docs:` to profile.yaml). Only slugs in
    the library are accepted — an unknown slug is rejected, not silently written."""
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(status_code=400, detail="agent id không hợp lệ")
    _require_agent(agent_id)
    from src.server import profile_editor

    valid = {d.slug for d in store.list_docs()}
    unknown = [s for s in slugs if s not in valid]
    if unknown:
        raise HTTPException(status_code=400, detail=f"tài liệu không có: {', '.join(unknown)}")
    chosen = [s for s in slugs if s in valid]

    text = profile_editor.read_profile_files(agent_id).get("profile", "")
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict):
        raise HTTPException(status_code=500, detail="profile.yaml hỏng")
    doc["company_docs"] = chosen
    try:
        profile_editor.save_profile_yaml(agent_id, yaml.safe_dump(doc, sort_keys=False,
                                                                  allow_unicode=True))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"lưu profile lỗi: {exc}") from None
    return {"ok": True, "company_docs": chosen}
