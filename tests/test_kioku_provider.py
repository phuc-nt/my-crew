"""v58 P7 (v19.5): kioku adapter — 7 điều kiện red-team, offline qua FAKE BIN.

Fake bin = shell script ghi lại argv/env rồi echo JSON định sẵn — pin đúng contract
subprocess (điều kiện 1/4/5) mà không cần bun. Điều kiện 3 (wrap untrusted) pin ở tầng
provider; điều kiện 6 (degrade) pin bằng bin thiếu/ok:false; điều kiện 7 (zero network)
là bằng chứng grep tại thời điểm tích hợp (ghi trong docstring adapter) + env allowlist
không mang proxy var — pin bằng test `_subprocess_env`.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path
from types import SimpleNamespace

from my_crew.memory import kioku_provider as kp
from my_crew.memory.provider import MemoryConfig, resolve_memory_text


def _fake_bin(tmp_path, response: dict, *, dump_env: bool = False) -> Path:
    """Script giả: log argv (+env nếu cần) vào file, in JSON response ra stdout."""
    log = tmp_path / "calls.log"
    envlog = tmp_path / "env.log"
    script = tmp_path / "my-kioku-fake"
    lines = ["#!/bin/sh", f'echo "$@" >> "{log}"']
    if dump_env:
        lines.append(f'env >> "{envlog}"')
    lines.append(f"cat <<'EOF'\n{json.dumps(response, ensure_ascii=False)}\nEOF")
    script.write_text("\n".join(lines), encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_resolve_bin_prefers_env_and_rejects_missing(tmp_path, monkeypatch):
    real = _fake_bin(tmp_path, {"ok": True, "data": {}})
    monkeypatch.setenv("MY_KIOKU_BIN", str(real))
    assert kp.resolve_bin() == str(real)
    monkeypatch.setenv("MY_KIOKU_BIN", str(tmp_path / "missing"))
    assert kp.resolve_bin() is None  # env đặt sai ⇒ None, không rơi ngầm sang PATH


def test_subprocess_env_is_exact_allowlist(tmp_path):
    env = kp._subprocess_env("/opt/bin/my-kioku", Path("/v"))
    assert set(env) == {"MY_KIOKU_VAULT", "PATH", "HOME"}  # đk 4+7: không key/proxy nào khác
    assert env["MY_KIOKU_VAULT"] == "/v"
    assert env["PATH"].startswith("/opt/bin")


def test_recall_formats_results_and_caps(tmp_path, monkeypatch):
    resp = {"ok": True, "data": {"results": [
        {"date": "2026-08-01", "body": "Dặn gửi hợp đồng cho anh Long"},
        {"date": "2026-08-02", "body": "Hẹn cà phê anh Tuấn 10h"},
        {"date": "2026-08-02", "body": ""},  # body rỗng bị bỏ
    ]}}
    monkeypatch.setenv("MY_KIOKU_BIN", str(_fake_bin(tmp_path, resp)))
    (tmp_path / "tk" / "vault" / ".kioku").mkdir(parents=True)
    out = kp.kioku_recall("tk", "hợp đồng", profiles_dir=tmp_path)
    assert out == ("- [2026-08-01] Dặn gửi hợp đồng cho anh Long\n"
                   "- [2026-08-02] Hẹn cà phê anh Tuấn 10h")


def test_recall_degrades_quietly(tmp_path, monkeypatch):
    monkeypatch.delenv("MY_KIOKU_BIN", raising=False)
    monkeypatch.setattr(kp, "_BUN_BIN", tmp_path / "absent")
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert kp.kioku_recall("tk", "x", profiles_dir=tmp_path) == ""  # bin thiếu (đk 6)
    bad = _fake_bin(tmp_path, {"ok": False, "error": "index hỏng"})
    monkeypatch.setenv("MY_KIOKU_BIN", str(bad))
    (tmp_path / "tk" / "vault" / ".kioku").mkdir(parents=True)
    assert kp.kioku_recall("tk", "x", profiles_dir=tmp_path) == ""  # ok:false ⇒ ""


def test_remember_inits_once_locks_and_writes(tmp_path, monkeypatch):
    fake = _fake_bin(tmp_path, {"ok": True, "data": {"entry_id": "e"}}, dump_env=True)
    monkeypatch.setenv("MY_KIOKU_BIN", str(fake))
    assert kp.kioku_remember("tk", "nhớ việc A", profiles_dir=tmp_path) is True
    calls = (tmp_path / "calls.log").read_text(encoding="utf-8").splitlines()
    assert calls[0].startswith("init")  # vault chưa có ⇒ init trước (trong flock)
    assert calls[1].startswith("remember --stdin")
    assert (tmp_path / "tk" / "vault" / ".my-crew.lock").exists()  # đk 5
    env_dump = (tmp_path / "env.log").read_text(encoding="utf-8")
    assert "OPENROUTER" not in env_dump and "TOKEN" not in env_dump  # đk 4 chạy thật


# --- provider seam ---


def _loaded(provider: str):
    return SimpleNamespace(
        profile_id="tk", memory="fact tĩnh", soul="", project="",
        memory_config=MemoryConfig(provider=provider),
    )


def test_provider_kioku_appends_wrapped_recall_on_query(monkeypatch):
    monkeypatch.setattr(
        "my_crew.memory.kioku_provider.kioku_recall",
        lambda pid, q, **kw: "- [2026-08-01] Dặn gửi hợp đồng",
    )
    out = resolve_memory_text(_loaded("kioku"), query="hợp đồng?")
    assert out.startswith("fact tĩnh")
    assert "Dặn gửi hợp đồng" in out
    assert "ký ức kioku" in out  # có label khối wrap (đk 3 — format_internal_content)


def test_provider_kioku_without_query_or_recall_is_static(monkeypatch):
    assert resolve_memory_text(_loaded("kioku")) == "fact tĩnh"  # không query ⇒ không recall
    monkeypatch.setattr(
        "my_crew.memory.kioku_provider.kioku_recall", lambda pid, q, **kw: ""
    )
    assert resolve_memory_text(_loaded("kioku"), query="x") == "fact tĩnh"  # degrade (đk 6)


def test_provider_static_ignores_query():
    assert resolve_memory_text(_loaded("static"), query="x") == "fact tĩnh"