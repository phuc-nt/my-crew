"""Đổi mật khẩu từ trong app — đường sửa duy nhất sau khi wizard tự khoá. Offline.

Các tính chất chịu lực:
- Phải ĐANG đăng nhập VÀ biết mật khẩu hiện tại (cookie trộm được vẫn không chiếm được
  tài khoản).
- Đổi thành công ⇒ hash mới VÀ session secret mới vào .env; secret mới là thứ giết mọi
  phiên cũ, nên nó quan trọng ngang hash.
- Auth đang tắt ⇒ 409, không lén bật auth lên bằng cách ghi hash.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from my_crew.server import auth, routes_auth_password


@pytest.fixture
def pw_env(tmp_path, monkeypatch):
    """`.env` dùng một lần + auth đang BẬT với mật khẩu biết trước."""
    env = tmp_path / ".env"
    env.write_text("OPENROUTER_MODEL=x\n", encoding="utf-8")
    monkeypatch.setattr("my_crew.server.env_writer._ENV_PATH", env)
    monkeypatch.setenv("WEB_AUTH_USERNAME", "ceo")
    monkeypatch.setenv("WEB_AUTH_PASSWORD_HASH", auth.hash_password("oldpass"))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-secret")
    monkeypatch.setattr(routes_auth_password, "_restart_web_service", lambda: True)
    auth._login_attempts.clear()
    return env


def _client():
    from my_crew.server.app import create_app

    return TestClient(create_app())


def _logged_in(client):
    r = client.post("/api/login", json={"username": "ceo", "password": "oldpass"})
    assert r.status_code == 200
    return client


def test_change_password_writes_new_hash_and_rotates_session_secret(pw_env):
    c = _logged_in(_client())
    r = c.post("/api/auth/change-password",
               json={"current_password": "oldpass", "new_password": "brandnew"})
    assert r.status_code == 200 and r.json()["ok"] is True
    text = pw_env.read_text(encoding="utf-8")
    hash_line = next(ln for ln in text.splitlines() if ln.startswith("WEB_AUTH_PASSWORD_HASH="))
    new_hash = hash_line.split("=", 1)[1]
    assert auth._verify("brandnew", new_hash)
    assert not auth._verify("oldpass", new_hash)
    # Secret mới là thứ đá các phiên khác ra; thiếu nó thì đổi mật khẩu vô nghĩa.
    secret_line = next(ln for ln in text.splitlines() if ln.startswith("WEB_SESSION_SECRET="))
    assert secret_line.split("=", 1)[1] not in ("", "test-secret")
    assert "OPENROUTER_MODEL=x" in text  # merge, không đạp file


def test_own_session_is_cleared_after_change(pw_env):
    c = _logged_in(_client())
    c.post("/api/auth/change-password",
           json={"current_password": "oldpass", "new_password": "brandnew"})
    # Người vừa đổi cũng phải đăng nhập lại — không ưu ái phiên nào.
    assert c.get("/api/agents").status_code == 401


def test_wrong_current_password_is_403_and_writes_nothing(pw_env):
    c = _logged_in(_client())
    before = pw_env.read_text(encoding="utf-8")
    r = c.post("/api/auth/change-password",
               json={"current_password": "notit", "new_password": "brandnew"})
    assert r.status_code == 403
    assert pw_env.read_text(encoding="utf-8") == before


def test_short_new_password_is_422(pw_env):
    c = _logged_in(_client())
    r = c.post("/api/auth/change-password",
               json={"current_password": "oldpass", "new_password": "abc"})
    assert r.status_code == 422
    assert "6" in r.json()["detail"]


def test_reusing_the_same_password_is_422(pw_env):
    c = _logged_in(_client())
    r = c.post("/api/auth/change-password",
               json={"current_password": "oldpass", "new_password": "oldpass"})
    assert r.status_code == 422


def test_no_session_is_401(pw_env):
    c = _client()  # chưa đăng nhập
    r = c.post("/api/auth/change-password",
               json={"current_password": "oldpass", "new_password": "brandnew"})
    assert r.status_code == 401


def test_auth_disabled_refuses_instead_of_silently_enabling_auth(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr("my_crew.server.env_writer._ENV_PATH", env)
    monkeypatch.delenv("WEB_AUTH_PASSWORD_HASH", raising=False)
    r = _client().post("/api/auth/change-password",
                       json={"current_password": "x", "new_password": "brandnew"})
    assert r.status_code == 409
    assert env.read_text(encoding="utf-8") == ""  # không ghi gì
