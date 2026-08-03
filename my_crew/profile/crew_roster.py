"""Crew roster (v58 P1) — cho thư ký biết đồng nghiệp trong crew là ai.

Yaml-peek đúng 3 trường (name/domain/web_search) từ `profiles/<id>/profile.yaml` cho các
agent ENABLED trong registry — KHÔNG `load_profile` đầy đủ per-agent (bài học M1 v56:
/staff nặng vì đúng lỗi này). Một profile hỏng/thiếu chỉ bị bỏ qua (log), không phá chat.

Tên agent là user-data tự do → defuse xuống một dòng + cap độ dài trước khi vào prompt
(cùng lý do capability block là INTERNAL-ONLY: không bao giờ tới external audience).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from my_crew.config.settings import MY_CREW_HOME

logger = logging.getLogger(__name__)

_NAME_MAX = 40
#: Cùng ràng buộc id với registry — chặn id lạ (traversal) trước khi ghép path.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _clean(text: str) -> str:
    """Một dòng, không backtick, bounded — user-data không được định dạng lại prompt."""
    return re.sub(r"[\r\n`]", " ", text).strip()[:_NAME_MAX]


def peek_profile_yaml(profile_id: str, *, profiles_dir: Path | None = None) -> dict:
    """Đọc THÔ profile.yaml của một agent — {} khi thiếu/hỏng/id lạ, không bao giờ raise.

    Dùng cho các chỗ chỉ cần vài trường rẻ (web_search, name, domain) — thay cho
    `load_profile` đầy đủ vốn dựng cả config/context (nợ M1 v56 ở /staff)."""
    if not _ID_RE.fullmatch(profile_id or ""):
        return {}
    base = profiles_dir if profiles_dir is not None else (MY_CREW_HOME / "profiles")
    try:
        doc = yaml.safe_load((base / profile_id / "profile.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.info("peek profile: bỏ qua %s (%s)", profile_id, exc)
        return {}
    return doc if isinstance(doc, dict) else {}


def crew_roster(
    exclude_id: str = "", *, registry_path: Path | None = None,
    profiles_dir: Path | None = None,
) -> list[dict]:
    """[{id, name, domain, web_search}] của agent enabled (registry + profile), sorted id."""
    from my_crew.runtime.registry import load_registry

    base = profiles_dir if profiles_dir is not None else (MY_CREW_HOME / "profiles")
    out: list[dict] = []
    for entry in load_registry(registry_path):
        if not entry.enabled or entry.id == exclude_id:
            continue
        doc = peek_profile_yaml(entry.id, profiles_dir=base)
        if not doc or doc.get("enabled") is False:
            continue
        out.append({
            "id": entry.id,
            "name": _clean(str(doc.get("name") or entry.id)),
            "domain": _clean(str(doc.get("domain") or "pm")),
            "web_search": bool(doc.get("web_search", False)),
        })
    return sorted(out, key=lambda a: a["id"])


def render_roster_lines(roster: list[dict]) -> list[str]:
    """Mỗi đồng nghiệp một dòng gọn: `  • id (Tên) — domain[, tra được web]`."""
    return [
        f"  • {a['id']} ({a['name']}) — {a['domain']}"
        + (", tra được web" if a["web_search"] else "")
        for a in roster
    ]
