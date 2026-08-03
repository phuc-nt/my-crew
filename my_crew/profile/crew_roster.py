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


def _clean(text: str) -> str:
    """Một dòng, không backtick, bounded — user-data không được định dạng lại prompt."""
    return re.sub(r"[\r\n`]", " ", text).strip()[:_NAME_MAX]


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
        path = base / entry.id / "profile.yaml"
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.info("crew roster: bỏ qua %s (%s)", entry.id, exc)
            continue
        if not isinstance(doc, dict) or doc.get("enabled") is False:
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
