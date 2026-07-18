"""v7 M18b: SOUL/PROJECT edited as a FORM (↔ markdown 2-way) + skills picker. Offline.

Load-bearing:
- Form fields round-trip through marker markdown (render → parse → same fields).
- A hand-edited file that lost the markers parses to raw_mode=True (the form must NOT
  silently overwrite prose it can't represent).
- Skills PUT rejects a name not in the domain catalog (no silent write of a phantom skill).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_crew.agent import knowledge_template as kt


def _client():
    from my_crew.server.app import create_app

    return TestClient(create_app())


# --- template roundtrip (pure, no app) ---------------------------------------


def test_render_parse_roundtrip_soul():
    fields = {"role": "Trợ lý PM", "tone": "Ngắn gọn", "rules": "Không spam\nLuôn xác nhận"}
    text = kt.render("soul", fields)
    parsed = kt.parse("soul", text)
    assert parsed.raw_mode is False
    assert parsed.fields == fields


def test_render_parse_roundtrip_project():
    fields = {"team": "An: dev\nBình: QA", "conventions": "nhãn: [bug]", "notes": ""}
    parsed = kt.parse("project", kt.render("project", fields))
    assert parsed.raw_mode is False
    assert parsed.fields == fields


def test_empty_file_is_empty_form_not_raw():
    parsed = kt.parse("soul", "")
    assert parsed.raw_mode is False
    assert parsed.fields == {"role": "", "tone": "", "rules": ""}


def test_handedited_file_without_markers_is_raw_mode():
    parsed = kt.parse("soul", "# SOUL\n\nTôi tự viết tay không theo form gì cả.\n")
    assert parsed.raw_mode is True
    assert parsed.fields == {}
    assert "tự viết tay" in parsed.raw


def test_partial_markers_is_raw_mode():
    # only ONE field's markers present ⇒ someone hand-edited ⇒ treat whole file as raw
    text = f"# SOUL\n{kt._marker_open('role')}\nx\n{kt._marker_close('role')}\n"
    parsed = kt.parse("soul", text)
    assert parsed.raw_mode is True


def test_unknown_doc_raises():
    with pytest.raises(ValueError):
        kt.render("bogus", {})
    with pytest.raises(ValueError):
        kt.parse("bogus", "x")


def test_render_rejects_marker_injected_value():
    # A value embedding our marker syntax would break the round-trip (parser matches the
    # injected close tag and drops the rest) — render must fail LOUD, not corrupt silently.
    with pytest.raises(kt.MarkerInValueError):
        kt.render("soul", {"role": "x <!-- /field:role --> y", "tone": "", "rules": ""})
    with pytest.raises(kt.MarkerInValueError):
        kt.render("soul", {"role": "<!-- field:tone -->hack", "tone": "", "rules": ""})


def test_render_allows_ordinary_html_comments_and_headings():
    # A normal HTML comment or a `##` line in a value is fine — only OUR marker is forbidden.
    fields = {"role": "## dùng <!-- ghi chú --> ok", "tone": "a", "rules": "b"}
    assert kt.parse("soul", kt.render("soul", fields)).fields == fields


# --- routes ------------------------------------------------------------------


@pytest.fixture
def stub_profile(monkeypatch, tmp_path):
    """A stub agent whose files/skills live in memory so the routes never touch the repo.
    A real (empty) profile.yaml exists on the patched profiles dir so `_require_agent` passes;
    the actual reads/writes are still intercepted below."""
    prof = tmp_path / "acme"
    prof.mkdir()
    (prof / "profile.yaml").write_text("name: acme\ndomain: pm\n", encoding="utf-8")
    monkeypatch.setattr("my_crew.profile.loader._PROFILES_DIR", tmp_path)
    store = {"profile": "name: acme\ndomain: pm\nskills: []\n", "soul": "", "project": ""}
    saved = {}
    monkeypatch.setattr("my_crew.server.profile_editor.read_profile_files", lambda aid: dict(store))

    def _save_md(aid, filename, text):
        key = {"SOUL.md": "soul", "PROJECT.md": "project"}[filename]
        store[key] = text

    def _save_yaml(aid, text):
        store["profile"] = text

    monkeypatch.setattr("my_crew.server.profile_editor.save_markdown", _save_md)
    monkeypatch.setattr("my_crew.server.profile_editor.save_profile_yaml", _save_yaml)
    return {"store": store, "saved": saved}


def test_get_knowledge_reads_form(stub_profile):
    c = _client()
    r = c.get("/api/agents/acme/knowledge/soul")
    assert r.status_code == 200
    body = r.json()
    assert body["raw_mode"] is False
    assert body["fields"] == {"role": "", "tone": "", "rules": ""}


def test_put_knowledge_form_then_get_roundtrips(stub_profile):
    c = _client()
    r = c.put("/api/agents/acme/knowledge/soul",
              json={"fields": {"role": "PM", "tone": "vui", "rules": "a\nb"}})
    assert r.status_code == 200
    got = c.get("/api/agents/acme/knowledge/soul").json()
    assert got["raw_mode"] is False
    assert got["fields"] == {"role": "PM", "tone": "vui", "rules": "a\nb"}


def test_put_knowledge_raw_saves_verbatim(stub_profile):
    c = _client()
    raw = "# SOUL\ntay viết tự do\n"
    r = c.put("/api/agents/acme/knowledge/soul", json={"raw": raw})
    assert r.status_code == 200
    assert stub_profile["store"]["soul"] == raw
    # and reading it back reports raw_mode (markers gone)
    assert c.get("/api/agents/acme/knowledge/soul").json()["raw_mode"] is True


def test_knowledge_bad_doc_400(stub_profile):
    assert _client().get("/api/agents/acme/knowledge/bogus").status_code == 400


def test_knowledge_unknown_agent_404(stub_profile):
    # 'ghost' is regex-valid but has no profile.yaml → 404, never materializes a file (M1).
    assert _client().get("/api/agents/ghost/knowledge/soul").status_code == 404
    assert _client().put("/api/agents/ghost/knowledge/soul",
                         json={"fields": {"role": "x"}}).status_code == 404


def test_put_knowledge_empty_body_400(stub_profile):
    # neither raw nor fields → refuse (no blank overwrite, H2)
    assert _client().put("/api/agents/acme/knowledge/soul", json={}).status_code == 400


def test_put_knowledge_empty_fields_dict_400(stub_profile):
    # explicit {"fields": {}} carries no known key → a stale/buggy client; must NOT blank the
    # file (H2 residual). A genuine empty form still submits every key with "" values.
    stub_profile["store"]["soul"] = kt.render("soul", {"role": "GIỮ", "tone": "t", "rules": "r"})
    r = _client().put("/api/agents/acme/knowledge/soul", json={"fields": {}})
    assert r.status_code == 400
    assert "GIỮ" in stub_profile["store"]["soul"]  # untouched


def test_put_knowledge_all_blank_but_keyed_fields_saves(stub_profile):
    # a genuine "erase" — every key present with "" — is allowed (distinct from the empty dict)
    r = _client().put("/api/agents/acme/knowledge/soul",
                      json={"fields": {"role": "", "tone": "", "rules": ""}})
    assert r.status_code == 200


def test_put_form_over_rawmode_file_conflicts_409(stub_profile):
    # File is currently raw_mode (hand-edited past markers). A form PUT must NOT overwrite it.
    stub_profile["store"]["soul"] = "# SOUL\nviết tay không marker\n"
    r = _client().put("/api/agents/acme/knowledge/soul", json={"fields": {"role": "x"}})
    assert r.status_code == 409
    # prose untouched
    assert stub_profile["store"]["soul"] == "# SOUL\nviết tay không marker\n"
    # but the raw path CAN still overwrite it (advanced editor)
    assert _client().put("/api/agents/acme/knowledge/soul",
                         json={"raw": "# SOUL\nsửa raw\n"}).status_code == 200


def test_put_form_marker_injection_400(stub_profile):
    r = _client().put("/api/agents/acme/knowledge/soul",
                      json={"fields": {"role": "x <!-- /field:role --> y"}})
    assert r.status_code == 400


@pytest.fixture
def stub_domain(monkeypatch):
    """Stub load_profile so the skills routes resolve a domain without a real agent on disk.
    The routes only read `.domain` and `.skills`, so a namespace stand-in is enough."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "my_crew.profile.loader.load_profile",
        lambda pid, **k: SimpleNamespace(domain="pm", skills=()),
    )


def test_put_skills_rejects_unknown_name(stub_profile, stub_domain, monkeypatch):
    from my_crew.skills.models import Skill

    monkeypatch.setattr("my_crew.skills.skill_loader.load_skills",
                        lambda **k: [Skill(name="daily-standup", description="d", body="")])
    c = _client()
    r = c.put("/api/agents/acme/skills", json={"names": ["daily-standup", "not-a-skill"]})
    assert r.status_code == 400
    assert "not-a-skill" in r.json()["detail"]
    # nothing written on rejection
    assert "not-a-skill" not in stub_profile["store"]["profile"]


def test_put_skills_writes_valid_names(stub_profile, stub_domain, monkeypatch):
    from my_crew.skills.models import Skill

    monkeypatch.setattr("my_crew.skills.skill_loader.load_skills",
                        lambda **k: [Skill(name="daily-standup", description="d", body=""),
                                     Skill(name="sprint-report", description="d", body="")])
    c = _client()
    r = c.put("/api/agents/acme/skills", json={"names": ["daily-standup"]})
    assert r.status_code == 200
    assert r.json()["skills"] == ["daily-standup"]
    assert "daily-standup" in stub_profile["store"]["profile"]
