"""Chỉ đạo giữa chừng cho một chuyến sprint đang chạy (v93 P4).

`data_dir/artifacts/team-tasks/<task_id>/steer.txt` — CEO ghi, `sprint_runner` đọc.

Vì sao là file chứ không phải một cột trong store: chuyến sprint chạy trong MỘT tiến
trình đã cầm sẵn hàng step của nó, và nó không đọc lại hàng ấy giữa chừng. Muốn chỉ
đạo tới được nó thì phải qua một chỗ nó CÓ đọc giữa chừng — thư mục artifact của
chính task, chỗ nó đang ghi kết quả vào. Thêm một cột nghĩa là thêm một lượt đọc DB
vào giữa vòng lặp chỉ để phục vụ một tính năng hiếm khi dùng tới.

Hợp đồng đọc-rồi-xoá: mỗi chỉ đạo áp đúng một lần. Chỉ đạo mới ghi đè chỉ đạo cũ
CHƯA áp — CEO gõ lại lần hai nghĩa là đổi ý, không phải muốn cộng dồn hai lời.

Best-effort tuyệt đối ở cả hai đầu: không đọc được thì chuyến sprint chạy tiếp như
chưa từng có chỉ đạo. Mất một lời dặn thì tiếc; làm hỏng cả việc vì một lời dặn đọc
không ra thì tệ hơn nhiều.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: Trần ký tự cho một chỉ đạo. Chỉ đạo đi thẳng vào acceptance của vòng kế, mà
#: acceptance nằm trong prompt của mọi vòng revise còn lại — một file to bất thường
#: (dán nhầm cả bản báo cáo) sẽ đẩy chính bản nháp đang sửa ra khỏi cửa sổ ngữ cảnh.
MAX_STEER_CHARS = 2000

#: Nhãn đặt trước chỉ đạo khi nối vào acceptance. Nói rõ hai điều model cần biết:
#: đây là lời của CEO (cùng cấp với đề bài, không phải dữ liệu tra cứu), và nó tới
#: SAU khi việc đã bắt đầu (nên có thể mâu thuẫn với đề — lời mới thắng).
STEER_LABEL = "CHỈ ĐẠO BỔ SUNG CỦA CEO (gửi lúc việc đang chạy — ưu tiên hơn đề ban đầu):"


def steer_path(data_dir: Path, task_id: str) -> Path:
    """`.../team-tasks/<task_id>/steer.txt`, chặn traversal qua `task_artifact_dir`."""
    from my_crew.agent.team_task_artifact import task_artifact_dir

    return task_artifact_dir(data_dir, task_id) / "steer.txt"


def write_steer(data_dir: Path, task_id: str, text: str) -> None:
    """Ghi (đè) chỉ đạo cho task. Ném ValueError nếu text rỗng hoặc task_id không hợp lệ.

    Ghi qua file tạm rồi `os.replace` vì runner có thể đọc bất cứ lúc nào: người đọc
    phải thấy hoặc chỉ đạo cũ, hoặc chỉ đạo mới trọn vẹn, không bao giờ thấy một file
    mới ghi được một nửa.
    """
    body = (text or "").strip()
    if not body:
        raise ValueError("chỉ đạo rỗng")
    path = steer_path(data_dir, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".txt.tmp")
    tmp.write_text(body[:MAX_STEER_CHARS], encoding="utf-8")
    os.replace(tmp, path)


def take_steer(data_dir: Path, task_id: str) -> str:
    """Đọc rồi XOÁ chỉ đạo. Trả "" khi không có gì, hoặc khi có lỗi bất kỳ.

    Xoá kể cả khi nội dung đọc ra rỗng/rác: một file không dùng được mà nằm lại sẽ
    được thử đọc lại ở mọi ranh giới còn lại của chuyến sprint, mỗi lần một dòng
    warning, mà không lần nào khá hơn lần đầu.
    """
    try:
        path = steer_path(data_dir, task_id)
        if not path.exists():
            return ""
        try:
            body = path.read_text(encoding="utf-8", errors="replace").strip()
        finally:
            path.unlink(missing_ok=True)
        return body[:MAX_STEER_CHARS]
    except Exception:  # noqa: BLE001 — xem docstring module
        logger.warning("sprint: không đọc được chỉ đạo giữa chừng", exc_info=True)
        return ""


def merge_steer(acceptance: str, steer: str) -> str:
    """Nối chỉ đạo vào acceptance, có nhãn. Không có chỉ đạo → trả acceptance nguyên vẹn."""
    body = (steer or "").strip()
    if not body:
        return acceptance
    base = (acceptance or "").strip()
    block = f"{STEER_LABEL}\n{body}"
    return f"{base}\n\n{block}" if base else block
