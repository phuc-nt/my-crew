"""Live check that a naturally-phrased delegation actually reaches `assign_team_task`.

The production failure this guards: the CEO messaged pong "Nghiên cứu giúp anh thị trường
xe máy điện Việt Nam 2026 ... Tổng hợp thành bảng so sánh", pong replied "Mình chưa hỗ
trợ yêu cầu đó qua chat" and no team task was ever created. The ops layer had the right
catalog and the right operator; the CLASSIFIER simply did not recognise the request.
Measured on the live model, 3 replays each, before the fix:

    "Nghiên cứu giúp anh ..."   unsupported | unsupported | assign_team_task
    "Khảo sát các công cụ ..."  question    | assign_team_task | unsupported
    "giao đội nghiên cứu ..."   assign_team_task ×3

Only the explicit "giao đội" phrasing was stable — and the CEO does not talk that way.
The cause was `assign_team_task`'s DESCRIPTION, not the intent prompt: it read "Giao một
việc lớn cho cả đội", so a research brief looked like an action with no matching command
(`unsupported`). Widening the description to name the work verbs took all three to 3/3.

This is deliberately a LIVE test. The defect is model behaviour under a prompt, and a
stubbed LLM cannot fail it — every offline test in `test_ops_chat.py` stayed green
through the entire production outage. The prompt/description TEXT contract is asserted
deterministically over in `test_ops_chat.py`; this file is the only thing that can catch
a wording change that keeps every keyword yet stops persuading the model.

Skipped unless OPENROUTER_API_KEY is configured (same gating as the other live suites).
"""

from __future__ import annotations

import pytest

try:
    from my_crew.config.config_builders import build_settings_from_env

    _settings = build_settings_from_env()
    _HAS_KEY = bool(getattr(_settings, "openrouter_api_key", None))
except Exception:
    _settings = None
    _HAS_KEY = False

pytestmark = pytest.mark.skipif(not _HAS_KEY, reason="OPENROUTER_API_KEY not configured")

#: The exact strings measured against the live model — the first two are what the CEO
#: actually sent and what actually failed, kept verbatim rather than paraphrased so a
#: regression is compared against the real production input.
_DELEGATIONS = [
    pytest.param(
        "Nghiên cứu giúp anh thị trường xe máy điện Việt Nam 2026. Cần biết: 3 hãng dẫn "
        "đầu thị phần, giá bán lẻ từng dòng chủ lực, và chính sách trợ giá/thuế của nhà "
        "nước năm nay. Tổng hợp thành bảng so sánh, ghi rõ nguồn cho từng số liệu.",
        id="loi-nho-va-tu-nhien",
    ),
    pytest.param(
        "Khảo sát các công cụ cho phép gửi tin nhắn Zalo OA tự động qua API: so sánh giá "
        "và giới hạn tin/tháng, gợi ý nên dùng cái nào",
        id="khao-sat-cong-cu",
    ),
    pytest.param(
        "giao đội nghiên cứu thị trường xe máy điện Việt Nam 2026, tổng hợp bảng so sánh",
        id="giao-doi-tuong-minh",
    ),
]


def _classify(message: str) -> dict:
    from my_crew.agent.ops_catalog import catalog_for_domain
    from my_crew.agent.ops_chat import classify_ops_intent
    from my_crew.llm.client import LlmClient

    # `personal` is pong's domain — the ORCHESTRATION subset, not the full admin catalog.
    # Classifying against the admin catalog would test a surface the CEO never reaches.
    return classify_ops_intent(LlmClient(_settings), message, catalog_for_domain("personal"))


@pytest.mark.parametrize("message", _DELEGATIONS)
def test_a_work_request_from_the_ceo_routes_to_assign_team_task(message):
    """No "giao"/"đội" required: a request that names work to be done must become a team
    task. Landing on `question` means the assistant answers alone; `unsupported` means it
    falls through to the M12 pack listing — both are the production failure."""
    result = _classify(message)

    assert result.get("intent") == "command", (
        f"delegation classified as {result.get('intent')!r} — the CEO's request would "
        "never become a team task"
    )
    assert result.get("command_id") == "assign_team_task"


def test_a_plain_question_is_not_swallowed_into_a_team_task():
    """The widened description must not turn ordinary chat into work: `assign_team_task`
    is a WRITE command, so a false positive here spends a confirm round-trip and, once
    confirmed, real money decomposing a non-task."""
    result = _classify("hôm nay thứ mấy vậy em")

    assert result.get("command_id") != "assign_team_task"


def test_a_readonly_fleet_query_still_routes_to_its_own_command():
    """`assign_team_task` names "so sánh"/"tổng hợp" now — the neighbouring commands must
    still win on their own turf rather than being absorbed by the broad one."""
    result = _classify("liệt kê các việc nhóm đang chạy")

    assert result.get("intent") == "command"
    assert result.get("command_id") == "list_team_tasks"
