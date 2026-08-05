"""v39 #1: Google Workspace READ tools (Gmail/Calendar/Drive) via the gws CLI.

Reads spawn the gws CLI with a CODE-fixed argv (LLM supplies only a query param, never an
argv) so a read can't become a write; results are bounded; a CLI failure degrades to a
string. In the toolset they are internal-only and flag-gated (off ⇒ byte-identical).
"""

from __future__ import annotations

import json

import pytest

from my_crew.tools import gws_read
from my_crew.tools.gws_read import (
    _READ_ALLOWLIST,
    GwsReadError,
    calendar_agenda,
    drive_list,
    gmail_triage,
)


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _fake_run(captured):
    def _run(argv, **kw):
        captured.append(argv)
        return _Proc(stdout='keyring-banner\n{"ok": true, "data": "x"}')
    return _run


def test_gmail_triage_uses_fixed_read_argv(monkeypatch):
    captured = []
    monkeypatch.setattr(gws_read.subprocess, "run", _fake_run(captured))
    out = gmail_triage()
    assert captured == [["gws", "gmail", "+triage", "--format", "json"]]  # code-fixed
    assert "ok" in out


def test_calendar_agenda_argv(monkeypatch):
    captured = []
    monkeypatch.setattr(gws_read.subprocess, "run", _fake_run(captured))
    calendar_agenda()
    assert captured == [["gws", "calendar", "+agenda", "--format", "json"]]


def test_drive_list_injects_only_query_param(monkeypatch):
    captured = []
    monkeypatch.setattr(gws_read.subprocess, "run", _fake_run(captured))
    drive_list("báo cáo")
    argv = captured[0]
    assert argv[:3] == ["gws", "drive", "files"] and argv[3] == "list"
    # The query rides a --params JSON, never as a raw argv token.
    params = json.loads(argv[argv.index("--params") + 1])
    assert "báo cáo" in params["q"]
    assert all(v not in argv for v in ("insert", "delete", "update", "send"))


def _fake_tasks(captured, items):
    def _run(argv, **kw):
        captured.append(argv)
        return _Proc(stdout=json.dumps({"kind": "tasks#tasks", "items": items}))
    return _run


def test_tasks_pending_asks_server_to_hide_completed(monkeypatch):
    captured = []
    monkeypatch.setattr(gws_read.subprocess, "run", _fake_tasks(captured, [
        {"title": "Gọi nha sĩ", "due": "2026-08-06T00:00:00.000Z", "status": "needsAction"},
        {"title": "Đã xong rồi", "status": "completed"},
    ]))
    out = gws_read.tasks_pending()
    argv = captured[0]
    assert argv[:4] == ["gws", "tasks", "tasks", "list"]  # code-fixed, `list` là read
    assert json.loads(argv[argv.index("--params") + 1]) == {
        "tasklist": "@default", "showCompleted": False, "maxResults": 100
    }
    assert out == "- Gọi nha sĩ (hạn 2026-08-06)"  # task đã xong không lọt vào bản kê


def test_tasks_pending_falls_back_to_notes_when_title_empty(monkeypatch):
    """Data thật của CEO có task tiêu đề rỗng, nội dung nằm ở `notes` — nếu chỉ đọc
    `title` thì bản kê ra dòng cụt "- " (hoặc mất mục). Dòng cuối rỗng cả hai thì bỏ."""
    monkeypatch.setattr(gws_read.subprocess, "run", _fake_tasks([], [
        {"title": "", "notes": "Huỷ dịch vụ Strava", "status": "needsAction"},
        {"title": "   ", "notes": "  ", "status": "needsAction"},
    ]))
    assert gws_read.tasks_pending() == "- Huỷ dịch vụ Strava"


def test_tasks_completed_filters_client_side_and_bounds_window(monkeypatch):
    """`completedMin` thu hẹp phía server nhưng response vẫn lẫn task chưa xong, nên
    lọc lại `status == completed`. Window bị kẹp để một `days` bậy không quét vô hạn."""
    captured = []
    monkeypatch.setattr(gws_read.subprocess, "run", _fake_tasks(captured, [
        {"title": "Nộp báo cáo", "status": "completed"},
        {"title": "Còn treo", "status": "needsAction"},
    ]))
    out = gws_read.tasks_completed(days=9999)
    params = json.loads(captured[0][captured[0].index("--params") + 1])
    assert params["showCompleted"] is True and params["showHidden"] is True
    assert params["completedMin"].endswith("Z")
    assert out == "- Nộp báo cáo"


def test_task_reads_bound_the_page_so_a_busy_list_does_not_hide_completed_work(monkeypatch):
    """Lọc `completed` chạy SAU khi API cắt trang, nên trang mặc định nhỏ (20) sẽ đẩy
    hết task đã xong ra ngoài và weekly báo "(không có)" — sai im lặng, không phải lỗi.
    Cả hai đường đọc task phải tự khai trần trang."""
    for call in (gws_read.tasks_pending, lambda: gws_read.tasks_completed(days=7)):
        captured = []
        monkeypatch.setattr(gws_read.subprocess, "run", _fake_tasks(captured, []))
        call()
        params = json.loads(captured[0][captured[0].index("--params") + 1])
        assert params["maxResults"] == 100


def test_tasks_empty_list_says_so_instead_of_blank(monkeypatch):
    monkeypatch.setattr(gws_read.subprocess, "run", _fake_tasks([], []))
    assert gws_read.tasks_pending() == "(không có)"


def test_tasks_cli_failure_raises_for_caller_to_degrade(monkeypatch):
    monkeypatch.setattr(gws_read.subprocess, "run",
                        lambda argv, **kw: _Proc(stderr="oauth expired", returncode=1))
    with pytest.raises(GwsReadError, match="lỗi"):
        gws_read.tasks_pending()


def test_read_allowlist_has_no_write_verbs():
    for prefix in _READ_ALLOWLIST.values():
        assert not any(v in prefix for v in ("send", "insert", "delete", "update", "+send"))


def test_cli_missing_raises_gwsreaderror(monkeypatch):
    def _boom(argv, **kw):
        raise FileNotFoundError("no gws")
    monkeypatch.setattr(gws_read.subprocess, "run", _boom)
    with pytest.raises(GwsReadError, match="chưa cài"):
        gmail_triage()


def test_nonzero_exit_raises(monkeypatch):
    monkeypatch.setattr(gws_read.subprocess, "run",
                        lambda argv, **kw: _Proc(stderr="oauth expired", returncode=1))
    with pytest.raises(GwsReadError, match="lỗi"):
        calendar_agenda()


# ---- toolset integration --------------------------------------------------

class _Cfg:
    pass


def test_toolset_off_by_default_no_gws():
    from my_crew.runtime_backends.read_only_toolset import build_read_toolset

    tools = build_read_toolset(_Cfg(), audience="internal")
    assert not any(n.startswith("gws.") for n in tools)  # byte-identical when flag off


def test_toolset_flag_on_adds_three_internal_tools():
    from my_crew.runtime_backends.read_only_toolset import build_read_toolset

    tools = build_read_toolset(_Cfg(), audience="internal", gws_context=True)
    assert {"gws.gmail", "gws.calendar", "gws.drive"} <= set(tools)


def test_toolset_external_audience_drops_gws():
    from my_crew.runtime_backends.read_only_toolset import build_read_toolset

    tools = build_read_toolset(_Cfg(), audience="external", gws_context=True)
    assert not any(n.startswith("gws.") for n in tools)  # internal-only, withheld externally


def test_gws_tool_degrades_on_error(monkeypatch):
    from my_crew.runtime_backends.read_only_toolset import build_read_toolset

    monkeypatch.setattr(gws_read.subprocess, "run",
                        lambda argv, **kw: (_ for _ in ()).throw(FileNotFoundError("no gws")))
    tools = build_read_toolset(_Cfg(), audience="internal", gws_context=True)
    out = tools["gws.calendar"]({})
    assert "gws calendar lỗi" in out  # string, not a crash


def test_gws_tools_never_reach_assert_read_only_as_write():
    from my_crew.runtime_backends.read_only_toolset import assert_read_only, build_read_toolset

    tools = build_read_toolset(_Cfg(), audience="internal", gws_context=True)
    assert_read_only(list(tools))  # no gws.* name trips the write/destructive guard
