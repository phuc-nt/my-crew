"""v58 P1: crew roster cho thư ký. Offline (tmp registry + profiles).

Load-bearing properties:

- Yaml-peek 3 trường, KHÔNG load_profile đầy đủ (bài học M1 v56); profile hỏng/thiếu bị
  bỏ qua có log, không raise.
- Lọc 2 tầng enabled (registry + profile), loại chính mình (exclude_id), sorted id.
- Tên user-data bị defuse xuống 1 dòng + cap 40 ký tự (không định dạng lại prompt).
- Capability block: CHỈ domain personal có roster; domain khác byte-identical; lỗi đọc
  roster ⇒ block như cũ (best-effort, không phá chat).
"""

from __future__ import annotations

import pytest

from my_crew.profile.capability_block import build_capability_block
from my_crew.profile.crew_roster import crew_roster, render_roster_lines


def _write_registry(tmp_path, ids_enabled: dict[str, bool]):
    lines = ["agents:"]
    for aid, en in ids_enabled.items():
        lines += [f"  - id: {aid}", f"    enabled: {'true' if en else 'false'}"]
    path = tmp_path / "registry.yaml"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _write_profile(tmp_path, aid, body: str):
    d = tmp_path / "profiles" / aid
    d.mkdir(parents=True)
    (d / "profile.yaml").write_text(body, encoding="utf-8")


@pytest.fixture()
def crew(tmp_path):
    reg = _write_registry(tmp_path, {"researcher": True, "tat": False, "hong": True,
                                      "tu-tat": True, "secretary": True})
    _write_profile(tmp_path, "researcher",
                   "name: Nghiên cứu\ndomain: office\nweb_search: true\n")
    _write_profile(tmp_path, "tat", "name: Đã tắt registry\ndomain: office\n")
    _write_profile(tmp_path, "hong", "name: [broken yaml\n  ::\n")
    _write_profile(tmp_path, "tu-tat", "name: Tự tắt\nenabled: false\ndomain: hr\n")
    _write_profile(tmp_path, "secretary", "name: Thư ký\ndomain: personal\n")
    return {"registry": reg, "profiles": tmp_path / "profiles"}


def test_roster_filters_and_peeks_cheaply(crew):
    roster = crew_roster("secretary", registry_path=crew["registry"],
                         profiles_dir=crew["profiles"])
    assert [a["id"] for a in roster] == ["researcher"]  # tắt/hỏng/tự-tắt/chính-mình loại hết
    assert roster[0] == {"id": "researcher", "name": "Nghiên cứu", "domain": "office",
                         "web_search": True}


def test_roster_defuses_freeform_name(tmp_path):
    reg = _write_registry(tmp_path, {"x": True})
    _write_profile(tmp_path, "x", 'name: "dòng1\\ndòng2 `backtick` ' + "y" * 60 + '"\n')
    roster = crew_roster(registry_path=reg, profiles_dir=tmp_path / "profiles")
    name = roster[0]["name"]
    assert "\n" not in name and "`" not in name and len(name) <= 40


def test_render_lines_show_capability(crew):
    lines = render_roster_lines(crew_roster("secretary", registry_path=crew["registry"],
                                            profiles_dir=crew["profiles"]))
    assert lines == ["  • researcher (Nghiên cứu) — office, tra được web"]


# --- capability block integration ---


class _LP:
    def __init__(self, domain):
        self.domain = domain
        self.profile_id = "secretary"
        self.skills = ()
        self.web_search = False
        self.memory_config = None


def test_capability_block_includes_roster_only_for_personal(monkeypatch):
    monkeypatch.setattr(
        "my_crew.profile.crew_roster.crew_roster",
        lambda exclude_id="", **kw: [{"id": "researcher", "name": "Nghiên cứu",
                                      "domain": "office", "web_search": True}],
    )
    personal = build_capability_block(_LP("personal"), None)
    assert "Đồng nghiệp trong crew" in personal
    assert "researcher (Nghiên cứu) — office, tra được web" in personal
    office = build_capability_block(_LP("office"), None)
    assert "Đồng nghiệp" not in office  # domain khác byte-identical


def test_capability_block_survives_roster_failure(monkeypatch):
    monkeypatch.setattr(
        "my_crew.profile.crew_roster.crew_roster",
        lambda exclude_id="", **kw: (_ for _ in ()).throw(RuntimeError("registry chết")),
    )
    block = build_capability_block(_LP("personal"), None)
    assert block.startswith("--- Năng lực nhân sự ---")  # không raise, block như cũ
    assert "Đồng nghiệp" not in block