"""v78 one-touch sprint→team upgrade: `upgrade_to_team`.

Chiều team→sprint đã có lưới tự động từ v77 (`downgrade_to_sprint`). Chiều ngược lại
thì không: sprint bế tắc chỉ được GỢI Ý "CEO giao lại bằng tiền tố `team:`" — nghĩa là
CEO phải tự gõ lại đề, và mọi thứ chuyến sprint đã làm ra (bản nháp dở, chỗ nó biết là
mình thiếu, lý do nó bỏ cuộc) rơi xuống đất. Việc chạy lại từ số không dù vừa trả tiền
cho một vòng tìm hiểu.

Lệnh này dựng một team task MỚI mang theo khối context đó. Ba lựa chọn thiết kế đáng
ghi lại:

  - Task mới, không phải hồi sinh task cũ. Kế hoạch sprint là DAG suy biến một đỉnh;
    biến nó thành DAG nhiều đỉnh giữa chừng nghĩa là sửa kế hoạch đã chốt hash, đúng
    thứ mà toàn bộ đường confirm-time tồn tại để cấm. Task cũ giữ nguyên trạng thái và
    lịch sử — nó là bằng chứng cho việc bộ định tuyến đã đoán chệch.
  - Context là THAM KHẢO, không phải kế hoạch. Kết quả dở dang do LLM sinh ra nên là
    nội dung không tin cậy bậc hai (cùng lý do `_review_evidence_block` bọc verdict):
    cắt ngắn rồi bọc qua `format_internal_content`, và prompt nói thẳng rằng đội tự
    quyết kế hoạch chứ không chép lại hướng đi đã chết.
  - Chuỗi nâng cấp chặn ở một lần. `previous_task` trong route record cho biết task
    này VỐN ĐÃ là kết quả của một lần nâng; nâng tiếp là vòng lặp đốt tiền không có
    đáy, nên tự động dừng lại và chỉ báo cho CEO.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Cắt trước khi bọc (thứ tự lấy từ `_review_evidence_block`): bọc rồi mới cắt sẽ xén
#: mất dấu đóng của khối delimiter và biến một khối được đánh dấu rõ ràng thành văn bản
#: trôi nổi giữa prompt.
_MAX_CONTEXT_CHARS = 2000

#: Prompt nói rõ khối dưới đây là gì và KHÔNG phải là gì. Không có câu này, decompose
#: đọc một bản nháp dở như thể đó là hướng đi đã được duyệt và chép lại đúng sai lầm
#: đã làm chuyến sprint chết.
_CONTEXT_HEADER = (
    "\n\n--- Bối cảnh: một lượt chạy nhanh (1 người) đã thử việc này và KHÔNG xong ---\n"
    "Dưới đây là kết quả dở dang và lý do dừng, CHỈ ĐỂ THAM KHẢO. Đội tự quyết kế "
    "hoạch mới: không mặc định đi lại đúng hướng đã chết, và không coi bản nháp dưới "
    "đây là kết quả đã được duyệt.\n"
)


def _sprint_context_block(task) -> str:
    """Khối context từ chuyến sprint đã chết, hoặc chuỗi rỗng.

    Garnish theo đúng tiền lệ `_review_evidence_block`: thiếu artifact, artifact hỏng,
    hay lỗi đọc đều trả rỗng — nâng cấp vẫn chạy với đề gốc trần. Một lần nâng cấp
    không bao giờ được hỏng chỉ vì phần bối cảnh cho thêm không đọc được.
    """
    try:
        from my_crew.agent.team_task_artifact import read_step_artifact
        from my_crew.runtime.team_task_paths import team_tasks_root
        from my_crew.tools.search_result_formatter import format_internal_content

        steps = getattr(task, "steps", None) or ()
        if not steps:
            return ""
        artifact = read_step_artifact(team_tasks_root(), task.id, steps[0].seq)
        if not artifact:
            return ""
        parts: list[str] = []
        draft = str(artifact.get("result_text") or "").strip()
        if draft:
            parts.append(f"Bản nháp dở dang:\n{draft}")
        # `self_check_failures` là chỗ vòng tự kiểm của chính bước đó ghi lại vì sao nó
        # tự thấy chưa đạt — chẩn đoán sát nhất về việc thiếu gì, do chính người vừa
        # làm viết ra.
        failures = artifact.get("self_check_failures")
        if isinstance(failures, (list, tuple)) and failures:
            listed = "\n".join(f"- {str(f).strip()}" for f in failures if str(f).strip())
            if listed:
                parts.append(f"Chỗ nó tự thấy chưa đạt:\n{listed}")
        if not parts:
            return ""
        body = "\n\n".join(parts)[:_MAX_CONTEXT_CHARS]
        wrapped = format_internal_content(body, label="sprint đã thử")
        return f"{_CONTEXT_HEADER}{wrapped}" if wrapped else ""
    except Exception:  # noqa: BLE001 — context là garnish, không bao giờ chặn nâng cấp
        logger.warning("upgrade_to_team: không dựng được khối context sprint (%s)",
                       getattr(task, "id", "?"), exc_info=True)
        return ""


def _reason_block(task) -> str:
    """Lý do chuyến sprint bỏ cuộc, lấy từ bản tổng kết giao cho CEO.

    `set_delivery(summary=...)` ghi vào `final_summary` — đó là nơi `stuck_decision`
    để lại câu "KHÔNG LÀM ĐƯỢC: ...", chẩn đoán cần nhất cho kế hoạch mới. Nó do LLM
    viết nên cũng phải bọc như mọi nội dung bậc hai khác.
    """
    summary = str(getattr(task, "final_summary", "") or "").strip()
    if not summary:
        return ""
    try:
        from my_crew.tools.search_result_formatter import format_internal_content

        wrapped = format_internal_content(summary[:_MAX_CONTEXT_CHARS], label="lý do dừng")
    except Exception:  # noqa: BLE001
        return ""
    return f"\nLý do dừng:\n{wrapped}\n" if wrapped else ""


def _already_upgraded(store, task_id: str) -> bool:
    """Task này có phải chính nó đã là kết quả của một lần nâng cấp không?

    Đây là cái chặn vòng lặp: nâng → chết → nâng → chết là chuỗi không đáy, mà mỗi
    mắt xích tốn trọn một lượt decompose cộng cả một chuyến chạy.
    """
    route = store.get_route(task_id)
    if not route:
        return False
    if route.get("source") == "upgrade" or route.get("previous_task"):
        return True
    previous = route.get("previous")
    return bool(isinstance(previous, dict) and previous.get("source") == "upgrade")


def _upgradable(task) -> bool:
    """Việc này có phải một chuyến sprint đã chết không."""
    steps = getattr(task, "steps", None) or ()
    return any(getattr(s, "step_type", "") == "sprint" for s in steps)


def preview_upgrade_to_team(slots: dict[str, str]) -> str:
    task_id = (slots.get("task_id") or "").strip()
    _load_upgradable(task_id).close()
    return (f"Mình sẽ giao lại việc `{task_id}` cho CẢ ĐỘI, mang theo kết quả dở dang "
            "của lượt chạy nhanh làm bối cảnh. Việc cũ giữ nguyên để đối chiếu.\n"
            "Xác nhận? (trả lời: xác nhận / huỷ)")


class _UpgradableTask:
    """Store + task đã qua đủ ba điều kiện tiên quyết của lệnh này."""

    def __init__(self, task_id: str) -> None:
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        self.store = TeamTaskStore(team_tasks_db_path())
        task = self.store.get(task_id)
        if task is None:
            self.store.close()
            raise ValueError(f"không tìm thấy việc đội `{task_id}`")
        if not _upgradable(task):
            self.store.close()
            raise ValueError(
                f"việc `{task.id}` không chạy chế độ nhanh (1 người) nên không có gì để "
                "nâng cấp — nếu kế hoạch cần sửa thì dùng `chỉnh kế hoạch`"
            )
        if task.status not in ("stalled", "cancelled"):
            self.store.close()
            raise ValueError(
                f"việc `{task.id}` đang ở trạng thái '{task.status}' — chỉ nâng cấp được "
                "khi lượt chạy nhanh đã dừng hẳn, không cắt ngang việc đang chạy"
            )
        if _already_upgraded(self.store, task.id):
            self.store.close()
            raise ValueError(
                f"việc `{task.id}` vốn đã là bản nâng cấp của một lượt chạy nhanh trước "
                "— nâng tiếp nữa chỉ lặp lại vòng cũ. Dùng `chỉnh kế hoạch` để đổi hướng"
            )
        self.task = task

    def close(self) -> None:
        self.store.close()


def _load_upgradable(task_id: str) -> _UpgradableTask:
    if not task_id:
        raise ValueError("cần mã việc cần nâng cấp")
    return _UpgradableTask(task_id)


def run_upgrade_to_team(slots: dict[str, str]) -> str:
    """Dựng một team task mới từ một chuyến sprint đã chết, mang theo bối cảnh."""
    task_id = (slots.get("task_id") or "").strip()
    ctx = _load_upgradable(task_id)
    try:
        task = ctx.task
        original = str(getattr(task, "original_request", "") or task.title).strip()
        context = _sprint_context_block(task) + _reason_block(task)
    finally:
        ctx.close()

    from my_crew.agent.ops_assign_team_task import preview_assign_team_task

    # `team:` là tiền tố ép chế độ của chính CEO — dùng lại nó thay vì mở một đường
    # riêng để bỏ qua bộ định tuyến. Một đường vòng riêng sẽ là chỗ duy nhất trong hệ
    # thống dựng được team task mà không đi qua `sprint_refusal`.
    new_slots: dict[str, str] = {"brief": f"team: {original}{context}"}
    for key in ("room_id",):
        if slots.get(key):
            new_slots[key] = slots[key]

    text = preview_assign_team_task(new_slots)
    new_id = new_slots.get("task_id", "")
    if new_id:
        _stamp_upgrade_route(new_id, previous_task=task_id)
        # Báo mã việc MỚI ngược lại cho người gọi. `preview_assign_team_task` chỉ ghi
        # vào `new_slots` — cái dict cục bộ này — nên nếu không chép ra, người gọi đọc
        # lại `slots["task_id"]` sẽ thấy y nguyên mã việc CŨ và tưởng nâng cấp trượt.
        # Đường autopilot trong `_sprint_upgrade_tail` đọc đúng chỗ này.
        slots["new_task_id"] = new_id
    # Đẩy nguyên phần preview lên: CEO vẫn thấy kế hoạch mới trước khi chốt, y như mọi
    # lần giao việc khác. Nâng cấp không phải lý do để bỏ qua cửa duyệt kế hoạch.
    return (f"Đã dựng lại việc `{task_id}` thành việc của cả đội, mang theo kết quả dở "
            f"dang làm bối cảnh.\n\n{text}")


def _stamp_upgrade_route(task_id: str, *, previous_task: str) -> None:
    """Ghi vào bản ghi định tuyến rằng task này ra đời từ một lần nâng cấp.

    Vừa là dữ liệu hồi cứu (`route_stats` đếm được), vừa là cái mà `_already_upgraded`
    đọc để chặn vòng lặp — nên nó phải ghi được, nhưng ghi hỏng thì cũng chỉ mất khả
    năng đếm chứ không được làm hỏng một task vừa dựng xong.
    """
    try:
        from my_crew.runtime.team_task_paths import team_tasks_db_path
        from my_crew.runtime.team_task_store import TeamTaskStore

        store = TeamTaskStore(team_tasks_db_path())
        try:
            route = store.get_route(task_id) or {}
            store.set_route(task_id, {**route, "source": "upgrade",
                                      "previous_task": previous_task})
        finally:
            store.close()
    except Exception:
        logger.warning("upgrade_to_team: không ghi được dấu nâng cấp cho %s",
                       task_id, exc_info=True)
