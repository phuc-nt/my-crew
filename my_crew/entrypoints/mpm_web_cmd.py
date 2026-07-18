"""`mpm web ...` — web-service operator helpers (v6 M16).

Currently one subcommand: `hash-password`, which turns a plaintext password into a bcrypt
hash to paste into `.env` as WEB_AUTH_PASSWORD_HASH. Reads the password from a prompt (not
argv) so it never lands in shell history.
"""

from __future__ import annotations

import getpass
import secrets
import sys


def run_web(sub: str, rest: list[str]) -> int:
    if sub == "hash-password":
        return _hash_password()
    if sub == "gen-secret":
        print(secrets.token_urlsafe(48))  # for WEB_SESSION_SECRET
        return 0
    print(f"usage: mpm web {{hash-password|gen-secret}} (got {sub!r})", file=sys.stderr)
    return 2


def _hash_password() -> int:
    from my_crew.server.auth import hash_password

    pw = getpass.getpass("Mật khẩu web (nhập ẩn): ")
    if not pw:
        print("error: mật khẩu trống", file=sys.stderr)
        return 2
    confirm = getpass.getpass("Nhập lại mật khẩu: ")
    if pw != confirm:
        print("error: hai lần nhập không khớp", file=sys.stderr)
        return 2
    print("\nDán dòng sau vào .env:")
    print(f"WEB_AUTH_PASSWORD_HASH={hash_password(pw)}")
    print("\nVà một session secret (nếu chưa có):")
    print(f"WEB_SESSION_SECRET={secrets.token_urlsafe(48)}")
    return 0
