"""Kioku memory adapter (v19.5 — thi công v58 P7): semantic recall qua CLI `my-kioku`.

Vault Obsidian-markdown per-agent tại `profiles/<id>/vault/` (user-data, gitignored);
index SQLite FTS5 là disposable, rebuild từ vault — không vector, không network.

7 điều kiện red-team (chốt ở plans/260711-1543-v19 §"Giữ cho v19.5") và cách đáp:
1. Dist qua `bun link` → resolve `MY_KIOKU_BIN` env, rồi PATH, rồi `~/.bun/bin/my-kioku`;
   TUYỆT ĐỐI không `bun x` (supply-chain: không kéo package lúc chạy).
2. Recall theo `<query>` cụ thể — không `--digest` toàn cục.
3. Nội dung recall là VAULT TEXT (untrusted) → call-site bọc `format_internal_content`.
4. Subprocess chạy với env ALLOWLIST cố định (`_subprocess_env`) — không kế thừa env đầy
   đủ, nên không một API key nào của my-crew lọt sang tiến trình bun.
5. flock per-vault quanh mọi lệnh GHI (remember/init) — listener + tick cùng agent không
   giẫm nhau; `reflect` không được schedule (YAGNI, chạy tay khi cần).
6. Health: bin thiếu/hỏng/timeout ⇒ degrade ("" hoặc False) + log — KHÔNG BAO GIỜ raise
   vào đường chat/briefing.
7. Zero network: my-kioku 0.5.0 src không có fetch/http (grep 2026-08-03, FTS5 thuần);
   env allowlist không mang proxy var nào nên dù có cũng không cấu hình nổi đường ra.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from my_crew.profile.loader import profile_memory_path

logger = logging.getLogger(__name__)

_TIMEOUT_S = 20
_RECALL_LIMIT = 5
_RECALL_CAP_CHARS = 3000
#: Fallback cuối khi PATH không có bin (bun link mặc định đặt ở đây).
_BUN_BIN = Path.home() / ".bun" / "bin" / "my-kioku"


def resolve_bin() -> str | None:
    """Đường dẫn bin my-kioku, hoặc None (chưa cài). Ưu tiên MY_KIOKU_BIN — không `bun x`."""
    env_bin = os.environ.get("MY_KIOKU_BIN", "").strip()
    if env_bin:
        return env_bin if Path(env_bin).exists() else None
    found = shutil.which("my-kioku")
    if found:
        return found
    return str(_BUN_BIN) if _BUN_BIN.exists() else None


def _subprocess_env(bin_path: str, vault: Path) -> dict[str, str]:
    """Env ALLOWLIST cho subprocess — đúng 3 khóa, không kế thừa gì khác (điều kiện 4).

    PATH chỉ gồm thư mục chứa bin (bun shim cần `bun` cạnh nó) + hệ thống tối thiểu;
    HOME vì bun đọc cache/config dưới ~; MY_KIOKU_VAULT trỏ vault của đúng agent."""
    return {
        "MY_KIOKU_VAULT": str(vault),
        "PATH": f"{Path(bin_path).parent}:/usr/bin:/bin",
        "HOME": str(Path.home()),
    }


def vault_path(profile_id: str, *, profiles_dir: Path | None = None) -> Path:
    """`profiles/<id>/vault/` — suy từ layout profile hiện có (user-data, gitignored)."""
    return profile_memory_path(profile_id, profiles_dir=profiles_dir).parent / "vault"


def _run(bin_path: str, vault: Path, args: list[str], *, stdin: str | None = None) -> dict | None:
    """Một lệnh my-kioku → dict `data` từ JSON `{ok, data}`, hoặc None (degrade, có log)."""
    try:
        proc = subprocess.run(  # noqa: S603 — argv list cố định, env allowlist, no shell
            [bin_path, *args, "--vault", str(vault)],
            input=stdin, capture_output=True, text=True, timeout=_TIMEOUT_S,
            env=_subprocess_env(bin_path, vault),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("kioku %s: %s", args[:1], exc)
        return None
    try:
        out = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        logger.warning("kioku %s: output không phải JSON (%.120s)", args[:1], proc.stdout)
        return None
    if not isinstance(out, dict) or not out.get("ok"):
        logger.warning("kioku %s: ok=false (%.120s)", args[:1], out.get("error", ""))
        return None
    data = out.get("data")
    return data if isinstance(data, dict) else {}


def kioku_recall(profile_id: str, query: str, *, profiles_dir: Path | None = None) -> str:
    """Recall theo query → text gọn "- [ngày] nội dung", "" khi không có gì/degrade.

    Caller PHẢI bọc kết quả bằng `format_internal_content` trước khi vào prompt
    (điều kiện 3 — vault text là dữ liệu không tin cậy)."""
    query = (query or "").strip()[:300]
    bin_path = resolve_bin()
    if not bin_path or not query:
        return ""
    vault = vault_path(profile_id, profiles_dir=profiles_dir)
    if not (vault / ".kioku").exists():
        return ""  # chưa có vault = chưa có ký ức, không phải lỗi
    data = _run(bin_path, vault, ["recall", query])
    if not data:
        return ""
    lines = [
        f"- [{r.get('date', '?')}] {str(r.get('body', '')).strip()}"
        for r in (data.get("results") or [])[:_RECALL_LIMIT]
        if str(r.get("body", "")).strip()
    ]
    return "\n".join(lines)[:_RECALL_CAP_CHARS]


def kioku_remember(profile_id: str, text: str, *, profiles_dir: Path | None = None) -> bool:
    """Ghi một entry nhật ký vào vault (flock per-vault; tự init lần đầu). False = degrade."""
    text = (text or "").strip()
    bin_path = resolve_bin()
    if not bin_path or not text:
        return False
    vault = vault_path(profile_id, profiles_dir=profiles_dir)
    vault.mkdir(parents=True, exist_ok=True)
    lock_file = vault / ".my-crew.lock"
    try:
        with lock_file.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)  # điều kiện 5 — single-writer per vault
            if not (vault / ".kioku").exists() and _run(bin_path, vault, ["init"]) is None:
                return False
            return _run(bin_path, vault, ["remember", "--stdin"], stdin=text) is not None
    except OSError as exc:
        logger.warning("kioku remember %s: %s", profile_id, exc)
        return False
