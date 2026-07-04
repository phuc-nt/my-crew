"""Flat-file store for the Company Docs library (v7 M19).

The CEO pastes company documents (processes, policies, directory, conventions) into a shared
library; each agent opts in to the docs it should read via a `company_docs:` list in its
profile.yaml (mirrors `skills:`). The opted-in bodies inject into the INTERNAL compose prompt
only — external reports/messages never see them (the P10 skills red line, reused).

Storage is flat `.md` files under `company-docs/` at the repo root (frontmatter `title` +
`updated`), NOT a DB and NOT RAG/embeddings — the company library is small (tens of docs) and
per-agent opt-in is enough selection. Git-friendly, covered by backup.sh, hand-editable by a
technical user. The name is deliberately distinct from the M18b per-agent "knowledge" form.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import yaml

from src.config.settings import REPO_ROOT

_DOCS_DIR = REPO_ROOT / "company-docs"

#: Reject a doc larger than this at write time — fail loud, don't silently truncate a doc.
MAX_DOC_CHARS = 50_000
#: A slug is our filename; keep it to a safe, predictable charset.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(frozen=True)
class CompanyDoc:
    slug: str  # filename stem == stable id
    title: str  # human title (frontmatter)
    updated: str  # ISO date string (frontmatter; "" if absent)
    body: str  # markdown body (no frontmatter)


class DocTooLargeError(ValueError):
    """A doc body exceeds MAX_DOC_CHARS — rejected at write, never stored truncated."""


class InvalidSlugError(ValueError):
    """A slug that isn't `[a-z0-9][a-z0-9-]*` — reject rather than touch an odd path."""


def slugify(title: str) -> str:
    """Title → a filesystem-safe slug (lowercase ascii, alnum + hyphen). Empty → 'doc'.

    Vietnamese (and other Latin) diacritics are folded to ASCII first (đ→d via an explicit
    map, then NFKD strips combining marks) so a Vietnamese title like "Quy trình nghỉ phép"
    yields a meaningful slug ("quy-trinh-nghi-phep") instead of collapsing to "doc" — the
    product is Vietnamese-first, so distinct titles must produce distinct slugs."""
    folded = title.strip().lower().replace("đ", "d")
    ascii_text = unicodedata.normalize("NFKD", folded).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return s or "doc"


def _docs_dir() -> Path:
    return _DOCS_DIR


def _path(slug: str) -> Path:
    if not _SLUG_RE.match(slug):
        raise InvalidSlugError(f"slug không hợp lệ: {slug!r}")
    return _docs_dir() / f"{slug}.md"


def _parse(text: str) -> tuple[dict, str]:
    """Split `---` frontmatter from the body (same shape as the skill loader)."""
    if not text.lstrip().startswith("---"):
        return {}, text
    stripped = text.lstrip()
    rest = stripped[3:]
    end = rest.find("\n---")
    if end == -1:
        return {}, text
    meta = yaml.safe_load(rest[:end]) or {}
    body = rest[end + 4:].strip()  # trim the fence's newline + trailing render newline
    return (meta if isinstance(meta, dict) else {}), body


def _render(title: str, updated: str, body: str) -> str:
    front = yaml.safe_dump({"title": title, "updated": updated},
                           sort_keys=False, allow_unicode=True)
    return f"---\n{front}---\n\n{body.strip()}\n"


def list_docs() -> list[CompanyDoc]:
    """All docs in the library, sorted by slug (deterministic). Missing dir ⇒ []."""
    d = _docs_dir()
    if not d.exists():
        return []
    out: list[CompanyDoc] = []
    for path in sorted(d.glob("*.md")):
        meta, body = _parse(path.read_text(encoding="utf-8"))
        out.append(CompanyDoc(slug=path.stem, title=str(meta.get("title") or path.stem),
                              updated=str(meta.get("updated") or ""), body=body))
    return out


def get_doc(slug: str) -> CompanyDoc | None:
    """One doc by slug, or None if absent."""
    path = _path(slug)
    if not path.exists():
        return None
    meta, body = _parse(path.read_text(encoding="utf-8"))
    return CompanyDoc(slug=slug, title=str(meta.get("title") or slug),
                      updated=str(meta.get("updated") or ""), body=body)


def save_doc(slug: str, *, title: str, body: str, updated: str) -> CompanyDoc:
    """Create/overwrite a doc (atomic). Rejects an over-size body (no silent truncation)."""
    if len(body) > MAX_DOC_CHARS:
        raise DocTooLargeError(
            f"Tài liệu {len(body)} ký tự, vượt giới hạn {MAX_DOC_CHARS}. Chia nhỏ tài liệu."
        )
    path = _path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text(_render(title, updated, body), encoding="utf-8")
    tmp.replace(path)  # atomic on same filesystem
    return CompanyDoc(slug=slug, title=title, updated=updated, body=body.strip())


def delete_doc(slug: str) -> bool:
    """Delete a doc; True if it existed. (The route layer confirms before calling.)"""
    path = _path(slug)
    if not path.exists():
        return False
    path.unlink()
    return True
