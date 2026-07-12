"""v31 P4 redline: native `gws_write` — the 3-prefix table and destructive-verb scan
are HARD categories at every gateway door in both trust modes; the handler re-enforces
the verdict before spawning, spawns argv-list/no-shell with a bounded timeout.
"""

from __future__ import annotations

import pytest

from src.actions.action_gateway import ActionGateway, HardBlockedError
from src.actions.gws_write import make_gws_handler
from src.actions.hard_block import BlockCategory, classify, needs_interrupt
from src.config.config_builders import build_settings_from_dict

_APPEND = ["sheets", "+append", "--spreadsheet", "SHEET1", "--values", "a,b,c"]
_CREATE = ["docs", "documents", "create", "--json", '{"title": "Báo cáo"}']
_WRITE = ["docs", "+write", "--document", "DOC1", "--text", "xin chào"]


def _settings(tmp_path, trust_mode):
    return build_settings_from_dict({
        "data_dir": tmp_path / "gw", "dry_run": False, "monthly_budget_usd": 50.0,
        "trust_mode": trust_mode,
    })


def _action(argv, **extra):
    return {"type": "gws_write", "argv": argv, **extra}


# --- classify ---


@pytest.mark.parametrize("argv", [_APPEND, _CREATE, _WRITE])
def test_allowed_prefixes_pass_lop_a(argv):
    assert classify(_action(argv)).blocked is False


@pytest.mark.parametrize("argv,category", [
    ([], BlockCategory.SECURITY),                                       # empty
    (["gmail", "send"], BlockCategory.SECURITY),                        # not in table
    (["sheets", "+read"], BlockCategory.SECURITY),                      # read isn't a write cmd
    (["sheets", "spreadsheets", "values", "update"], BlockCategory.SECURITY),
    (["docs", "documents", "get"], BlockCategory.SECURITY),
    (["sheets", "+append", "--spreadsheet", "X", "--values", "a", "delete"],
     BlockCategory.DATA_LOSS),                                          # destructive verb
    (["drive", "files", "trash"], BlockCategory.DATA_LOSS),
    (["sheets", "spreadsheets", "batchClear"], BlockCategory.DATA_LOSS),
    (["drive", "permissions", "create"], BlockCategory.SECURITY),       # visibility change
    (["docs", "+write", "--document", "D", "--text", "share publicly", "--share"],
     BlockCategory.SECURITY),
])
def test_out_of_table_and_destructive_are_hard_categories(argv, category):
    verdict = classify(_action(argv))
    assert verdict.blocked
    assert verdict.category == category  # NEVER NOT_ALLOWLISTED (F1)


def test_credential_in_argv_denied():
    key = "OPENROUTER_API_KEY=" + "sk" + "-or-v1-" + "abcdef1234567890abcdef"
    verdict = classify(_action(["docs", "+write", "--document", "D", "--text", key]))
    assert verdict.blocked and verdict.category == BlockCategory.CREDENTIAL


def test_needs_interrupt_internal_lop_b():
    v = needs_interrupt(_action(_APPEND))
    assert v.interrupt is True


# --- gateway doors, both trust modes ---


@pytest.mark.parametrize("trust_mode", ["autonomous", "guarded"])
def test_out_of_table_denied_via_execute_and_approved(tmp_path, trust_mode):
    gw = ActionGateway(_settings(tmp_path, trust_mode))
    try:
        with pytest.raises(HardBlockedError):
            gw.execute(_action(["gmail", "send"]), handler=lambda a: "boom")
        with pytest.raises(HardBlockedError):
            gw.execute_approved(_action(["drive", "files", "trash"]),
                                handler=lambda a: "boom")
    finally:
        gw.close()


def test_guarded_queues_autonomous_runs(tmp_path):
    gw = ActionGateway(_settings(tmp_path / "g", "guarded"))
    try:
        assert gw.execute(_action(_APPEND), handler=lambda a: "x").status == "pending_approval"
    finally:
        gw.close()
    gw = ActionGateway(_settings(tmp_path / "a", "autonomous"))
    try:
        assert gw.execute(_action(_APPEND), handler=lambda a: "ran").status == "executed"
    finally:
        gw.close()


# --- handler: re-enforce + spawn behavior (fake gws binary) ---


def _fake_gws(tmp_path, script_body):
    binpath = tmp_path / "fake-gws"
    binpath.write_text("#!/bin/sh\n" + script_body, encoding="utf-8")
    binpath.chmod(0o755)
    return str(binpath)


def test_handler_refuses_out_of_table_before_spawn(tmp_path):
    ran_marker = tmp_path / "ran"
    bin_ = _fake_gws(tmp_path, f"touch {ran_marker}\necho '{{}}'\n")
    with pytest.raises(PermissionError, match="gws_write refused"):
        make_gws_handler(bin_)(_action(["gmail", "send"]))
    assert not ran_marker.exists()  # never spawned


def test_handler_parses_append_summary(tmp_path):
    out = '{"updates": {"updatedCells": 3, "updatedRange": "Sheet1!A5:C5"}}'
    bin_ = _fake_gws(tmp_path, f"echo '{out}'\n")
    summary = make_gws_handler(bin_)(_action(_APPEND))
    assert "appended 3 cells" in summary and "Sheet1!A5:C5" in summary


def test_handler_parses_doc_create_summary(tmp_path):
    out = '{"documentId": "DOC42", "title": "Báo cáo"}'
    bin_ = _fake_gws(tmp_path, f"echo '{out}'\n")
    summary = make_gws_handler(bin_)(_action(_CREATE))
    assert "created document DOC42" in summary


def test_handler_surfaces_cli_failure(tmp_path):
    bin_ = _fake_gws(tmp_path, "echo 'token expired' >&2\nexit 3\n")
    with pytest.raises(RuntimeError, match="gws exited 3: token expired"):
        make_gws_handler(bin_)(_action(_APPEND))


def test_handler_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("src.actions.gws_write._GWS_TIMEOUT_S", 1)
    bin_ = _fake_gws(tmp_path, "sleep 5\n")
    with pytest.raises(RuntimeError, match="timed out"):
        make_gws_handler(bin_)(_action(_APPEND))


# --- catalog + dispatch ---


def test_hr_pack_ships_gws_catalog():
    from src.packs.registry import PackRegistry

    commands = PackRegistry().load("hr").commands
    assert {"append_sheet_row", "create_doc", "write_doc"} <= set(commands)
    assert all(commands[c]["type"] == "gws_write"
               for c in ("append_sheet_row", "create_doc", "write_doc"))


def test_append_args_pin_configured_sheet(monkeypatch):
    from src.packs.registry import PackRegistry

    monkeypatch.setenv("HR_SHEET_ID", "PINNED_SHEET")
    build = PackRegistry().load("hr").commands["append_sheet_row"]["build_args"]
    payload = build({"values": "a,b"}, config=object())
    assert payload["argv"][:4] == ["sheets", "+append", "--spreadsheet", "PINNED_SHEET"]
    assert payload["dedup_hint"].startswith("sheet-append:a,b:")


def test_shared_dispatch_routes_gws(tmp_path, monkeypatch):
    from src.actions.approved_dispatch import dispatch_approved_action

    bin_ = _fake_gws(tmp_path, "echo '{}'\n")
    monkeypatch.setattr("src.actions.gws_write.make_gws_handler",
                        lambda gws_bin="gws": make_gws_handler(bin_))
    summary = dispatch_approved_action(_action(_APPEND), config=object())
    assert summary.startswith("gws sheets +append")
