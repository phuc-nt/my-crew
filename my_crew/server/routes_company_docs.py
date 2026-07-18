"""Web CRUD for the Company Docs library (v7 M19). Session-auth-gated.

The CEO manages the shared document library here: list / read / create / update / delete flat
`.md` docs under `company-docs/`. Per-agent opt-in (which agent reads which doc) lives on the
agent page (routes_agent_company_docs) — this router owns the library itself.

Writes go straight to the flat-file store (no gateway): editing a company document is a local
config write, same trust level as the profile editor (M18b), NOT an outward action.
"""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from my_crew.company_docs import store

router = APIRouter(prefix="/api/company-docs", tags=["company-docs"])


def _view(doc: store.CompanyDoc) -> dict:
    return {"slug": doc.slug, "title": doc.title, "updated": doc.updated, "body": doc.body}


@router.get("")
def list_company_docs() -> dict:
    """All docs (metadata + body). Small library ⇒ returning bodies is fine (no pagination)."""
    return {"docs": [_view(d) for d in store.list_docs()]}


@router.get("/{slug}")
def get_company_doc(slug: str) -> dict:
    try:
        doc = store.get_doc(slug)
    except store.InvalidSlugError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if doc is None:
        raise HTTPException(status_code=404, detail=f"không tìm thấy tài liệu {slug!r}")
    return _view(doc)


@router.post("")
def create_company_doc(title: str = Body(..., embed=True),  # noqa: B008
                       body: str = Body(default="", embed=True),  # noqa: B008
                       updated: str = Body(default="", embed=True)) -> dict:  # noqa: B008
    """Create a doc; slug derived from the title. A title colliding with an existing slug is
    rejected (409) so a create never silently overwrites another doc — use PUT to edit."""
    title = str(title).strip()
    if not title:
        raise HTTPException(status_code=400, detail="cần tiêu đề")
    slug = store.slugify(title)
    if store.get_doc(slug) is not None:
        raise HTTPException(status_code=409, detail=f"đã có tài liệu với slug {slug!r}")
    try:
        doc = store.save_doc(slug, title=title, body=str(body), updated=str(updated))
    except store.DocTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _view(doc)


@router.put("/{slug}")
def update_company_doc(slug: str, title: str = Body(..., embed=True),  # noqa: B008
                       body: str = Body(default="", embed=True),  # noqa: B008
                       updated: str = Body(default="", embed=True)) -> dict:  # noqa: B008
    """Overwrite an existing doc. 404 if it doesn't exist (create uses POST). The slug is the
    stable id — renaming the title does NOT move the file (avoids breaking agent opt-ins)."""
    try:
        if store.get_doc(slug) is None:
            raise HTTPException(status_code=404, detail=f"không tìm thấy tài liệu {slug!r}")
        doc = store.save_doc(slug, title=str(title).strip() or slug, body=str(body),
                             updated=str(updated))
    except store.InvalidSlugError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except store.DocTooLargeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return _view(doc)


@router.delete("/{slug}")
def delete_company_doc(slug: str) -> dict:
    """Delete a doc. (The UI confirms first.) Agents still opting into it will simply drop it
    at load — a dangling opt-in is warned and skipped, never a crash."""
    try:
        existed = store.delete_doc(slug)
    except store.InvalidSlugError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if not existed:
        raise HTTPException(status_code=404, detail=f"không tìm thấy tài liệu {slug!r}")
    return {"ok": True}
