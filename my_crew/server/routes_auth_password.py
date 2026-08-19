"""Đổi mật khẩu đăng nhập từ trong app (không phải chỉ lúc chạy wizard lần đầu).

Trước module này, mật khẩu chỉ đặt được một lần — ở bước `finish` của Setup Wizard, mà
wizard tự khoá lại (410) sau khi setup xong. Người vận hành lỡ tay lộ mật khẩu chỉ còn
đường sửa `.env` bằng tay rồi restart service. Route này mở đúng một lối: người ĐANG
đăng nhập, biết mật khẩu hiện tại, đổi sang mật khẩu mới.

Hai tính chất an toàn:

1. **Phải biết mật khẩu cũ.** Cookie phiên bị trộm vẫn không đủ để chiếm tài khoản —
   kẻ cầm cookie không đổi được mật khẩu nếu không biết mật khẩu hiện tại.
2. **Đổi mật khẩu thì mọi phiên chết theo.** Cùng lúc ghi lại `WEB_SESSION_SECRET` mới,
   nên chữ ký cookie cũ hết hiệu lực. Đây là điểm chính: người ta đổi mật khẩu vì nghi
   có kẻ khác đang đăng nhập — nếu phiên của kẻ đó vẫn sống thì đổi để làm gì.

Vì secret chỉ bind một lần lúc dựng app, phiên cũ thực sự chết sau khi service restart
(giống bước `finish`). Handler trả `restarting` để FE biết phải nói người dùng đợi.

Tách khỏi `auth.py` vì file đó đã sát ngưỡng 200 dòng và giữ đúng một việc: gác cổng.
"""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Body, HTTPException, Request

from my_crew.server import auth, env_writer
from my_crew.server.env_writer import FINISH_WRITABLE_KEYS

#: Cùng sàn với bước `finish` của wizard — đổi mật khẩu không được phép yếu hơn lúc đặt.
MIN_PASSWORD_LEN = 6

router = APIRouter(tags=["auth"])


@router.post("/api/auth/change-password")
def change_password(
    request: Request,
    current_password: str = Body(..., embed=True),
    new_password: str = Body(..., embed=True),
) -> dict:
    """Đổi mật khẩu đăng nhập; đá mọi phiên hiện có bằng session secret mới."""
    if not auth.auth_enabled():
        # Auth đang tắt (dev localhost): không có mật khẩu để đổi. Nói thẳng thay vì
        # ghi một hash vào .env rồi bật auth lên sau lưng người dùng.
        raise HTTPException(
            status_code=409,
            detail=(
                "Chưa bật đăng nhập nên không có mật khẩu để đổi. "
                "Chạy phần cài đặt ban đầu trước."
            ),
        )
    if not request.session.get("user"):
        raise HTTPException(status_code=401, detail="Cần đăng nhập trước khi đổi mật khẩu.")
    if not auth.verify_current_password(current_password):
        raise HTTPException(status_code=403, detail="Mật khẩu hiện tại không đúng.")
    if len(new_password) < MIN_PASSWORD_LEN:
        raise HTTPException(
            status_code=422,
            detail=f"Mật khẩu mới tối thiểu {MIN_PASSWORD_LEN} ký tự.",
        )
    if new_password == current_password:
        raise HTTPException(status_code=422, detail="Mật khẩu mới phải khác mật khẩu hiện tại.")

    env_writer.merge_env(
        {
            "WEB_AUTH_PASSWORD_HASH": auth.hash_password(new_password),
            "WEB_SESSION_SECRET": secrets.token_urlsafe(48),
        },
        allow=FINISH_WRITABLE_KEYS,
    )
    # Xoá phiên của chính người vừa đổi: họ phải đăng nhập lại bằng mật khẩu mới, giống
    # mọi phiên khác. Không ưu ái phiên nào.
    request.session.clear()
    restarting = _restart_web_service()
    return {
        "ok": True,
        "restarting": restarting,
        "message": (
            "Đã đổi mật khẩu. Đang khởi động lại dịch vụ — đợi ~5 giây rồi đăng nhập lại."
            if restarting
            else "Đã đổi mật khẩu. Khởi động lại dịch vụ web rồi đăng nhập lại bằng mật khẩu mới."
        ),
    }


def _restart_web_service() -> bool:
    """Nhờ launchd nạp lại .env. Dùng chung đường với wizard để chỉ có một cách restart."""
    from my_crew.server.routes_setup import _restart_web_service as _restart

    return bool(_restart())


__all__ = ["router", "change_password", "MIN_PASSWORD_LEN"]
