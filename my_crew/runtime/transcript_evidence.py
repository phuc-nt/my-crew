"""Trích "bằng chứng quá trình" từ transcript của một attempt cho peer review (v80 P3).

Review chấm QUÁ TRÌNH thật thay vì chỉ tin bản giao: tool nào đã gọi, nguồn nào đã
thật sự mở, usage tổng — để tiêu chí "số liệu có nguồn" verify được bằng tool_result
thật thay vì tin lời văn (bài học v72: bảng giá bịa well-formed qua mặt cả 3 grader).

Thuần hàm đọc, không state. Parse tolerant: dòng JSONL hỏng bị bỏ qua (transcript là
best-effort, một attempt chết giữa chừng để lại dòng cụt là bình thường). Transcript
vắng mặt → None → prompt review y hệt trước phase này; consumer KHÔNG được suy diễn
"thiếu transcript = có lỗi". Cap cứng theo setting để giữ triết lý review rẻ mặc định
(transcript dài gấp 10–50 lần bản giao — không bao giờ nhét nguyên văn vào prompt).

Resolve file theo `*-<locked_version>.jsonl` chứ KHÔNG theo step_id: round ≥1 chấm
artifact của rework row (step_id khác), còn `locked_version` luôn là `attempt_id` của
đúng bản DONE đang chấm — UUID, duy nhất, không có khái niệm "attempt cao nhất".
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Per-item trims — nhiều nguồn cùng lọt vào cap tổng thay vì một result nuốt hết.
_ARGS_CHARS = 200
_RESULT_CHARS = 500
_TRUNCATED_MARK = "\n…[bằng chứng bị cắt theo cap]"


def find_transcript_for_version(
    data_dir: Path, task_id: str, locked_version: str
) -> Path | None:
    """Transcript file của đúng attempt đang chấm, hoặc None (bước cũ/recorder tắt)."""
    from my_crew.runtime.step_recorder import _SEGMENT_RE, transcripts_dir

    if not locked_version or not _SEGMENT_RE.match(locked_version):
        return None
    try:
        matches = sorted(
            transcripts_dir(Path(data_dir), task_id).glob(f"*-{locked_version}.jsonl")
        )
    except (ValueError, OSError):  # task_id không an toàn / IO — coi như không có
        return None
    return matches[0] if matches else None


def parse_transcript_events(path: Path) -> list[dict]:
    """Đọc tolerant một transcript JSONL: dòng hỏng bị bỏ, IO lỗi → [] (best-effort).

    Public: route transcript-tab (v82) cũng đọc qua đây — một chỗ duy nhất quyết định
    thế nào là "dòng hợp lệ"."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    events: list[dict] = []
    for line in raw.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def summarize_transcript_usage(path: Path) -> dict | None:
    """Tổng usage LLM của một transcript — nguồn cho bench đo per-step (v80 P5).

    Trả `{llm_calls, prompt_tokens, completion_tokens, cost_usd, models}` hoặc None
    khi file vắng/không có event nào. LƯU Ý: với deep tier, `llm_response` là event
    TỔNG HỢP cuối loop (aggregate) — số đo là per-step/per-attempt, không hứa
    per-exchange. Ledger (`cost_usd` trong store) vẫn là nguồn sự thật kế toán;
    transcript chỉ cho phân rã chi tiết.
    """
    events = parse_transcript_events(path)
    if not events:
        return None
    usage = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
             "cost_usd": 0.0, "models": []}
    for event in events:
        if event.get("t") != "llm_response":
            continue
        usage["llm_calls"] += 1
        usage["prompt_tokens"] += int(event.get("prompt_tokens") or 0)
        usage["completion_tokens"] += int(event.get("completion_tokens") or 0)
        usage["cost_usd"] += float(event.get("cost_usd") or 0.0)
        model = str(event.get("model") or "")
        if model and model not in usage["models"]:
            usage["models"].append(model)
    return usage


def extract_task_behavior_summary(
    data_dir: Path, task_id: str, max_chars: int
) -> str | None:
    """Tóm tắt HÀNH VI quá trình của cả task cho reflection (v80 P5) — chỉ tên + số đếm.

    Khác evidence cho review: KHÔNG nhúng args/kết quả tool hay query prefetch — đó là
    nội dung attacker có thể ảnh hưởng, còn output reflection ghi vào memory bền mà mọi
    sibling đọc được (threat model trong `task_reflection._task_digest`). Tên tool là
    định danh do runtime đăng ký, số đếm là số đếm — đủ để bài học kiểu "gọi web_search
    6 lần cho một bước" mà không mở đường injection.

    None khi không có transcript nào parse được (reflection giữ prompt cũ y hệt).
    """
    if max_chars <= 0:
        return None
    from my_crew.runtime.step_recorder import transcripts_dir

    try:
        files = sorted(transcripts_dir(Path(data_dir), task_id).glob("*.jsonl"))
    except (ValueError, OSError):
        return None

    tool_counts: dict[str, int] = {}
    prefetches = 0
    fetches = 0
    attempts = 0
    usage_totals = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
    parsed_any = False
    for path in files:
        events = parse_transcript_events(path)
        if not events:
            continue
        parsed_any = True
        attempts += 1
        for event in events:
            kind = event.get("t")
            if kind == "tool_call":
                name = str(event.get("name") or "?")
                tool_counts[name] = tool_counts.get(name, 0) + 1
            elif kind == "prefetch":
                prefetches += 1
            elif kind == "fetch":
                # Count only, no URLs — same threat model as prefetch queries above.
                if not event.get("skipped"):
                    fetches += 1
            elif kind == "llm_response":
                usage_totals["llm_calls"] += 1
                usage_totals["prompt_tokens"] += int(event.get("prompt_tokens") or 0)
                usage_totals["completion_tokens"] += int(event.get("completion_tokens") or 0)
    if not parsed_any:
        return None

    tools_text = (
        ", ".join(f"{name} ×{n}" for name, n in sorted(tool_counts.items()))
        or "không gọi tool nào"
    )
    lines = [
        f"- {attempts} attempt có transcript; tool: {tools_text}; "
        f"prefetch web ×{prefetches}; đọc trang chính thức ×{fetches}.",
        f"- {usage_totals['llm_calls']} lượt LLM, "
        f"{usage_totals['prompt_tokens']} prompt + "
        f"{usage_totals['completion_tokens']} completion tokens.",
    ]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: max(0, max_chars - len(_TRUNCATED_MARK))] + _TRUNCATED_MARK
    return text


def _append_content(lines: list[str], event: dict) -> None:
    """Thêm dòng nội dung thật của một prefetch/fetch round, nếu transcript có ghi.

    Byte count chứng minh trang ĐÃ mở, không chứng minh con số nào nằm trên trang đó —
    reviewer không đối chiếu được `65.000 ₫` với `bytes: 18079`. Vắng `content_head`
    (transcript cũ, hoặc round bị bỏ qua) ⇒ không thêm gì, KHÔNG suy diễn.
    """
    content = str(event.get("content_head") or "").strip()
    if content:
        lines.append(f"  → nội dung: {content[:_RESULT_CHARS]}")


def extract_review_evidence(path: Path, max_chars: int) -> str | None:
    """Render transcript thành text gọn cho prompt review, cắt theo `max_chars`.

    None khi cap ≤ 0, file không đọc được, hoặc không parse được event nào.
    """
    if max_chars <= 0:
        return None
    events = parse_transcript_events(path)
    if not events:
        return None

    tool_lines: list[str] = []
    prompt_tokens = 0
    completion_tokens = 0
    cost_usd = 0.0
    models: list[str] = []
    llm_calls = 0
    for event in events:
        kind = event.get("t")
        if kind == "tool_call":
            args = str(event.get("args_head") or "")[:_ARGS_CHARS]
            tool_lines.append(f"- gọi tool {event.get('name')}: {args}")
        elif kind == "tool_result":
            content = str(event.get("content_head") or "")[:_RESULT_CHARS]
            tool_lines.append(f"  → kết quả {event.get('name')}: {content}")
        elif kind == "prefetch":
            queries = ", ".join(str(q) for q in (event.get("queries") or []))
            tool_lines.append(
                f"- prefetch web ({event.get('bytes')} bytes): {queries}"
            )
            _append_content(tool_lines, event)
        elif kind == "fetch":
            # Which official pages were actually OPENED is the evidence a reviewer needs
            # to judge source quality — the axis this whole round exists to move. A
            # skipped round says so explicitly rather than showing an empty list.
            urls = ", ".join(str(u) for u in (event.get("urls") or []))
            skipped = str(event.get("skipped") or "")
            tool_lines.append(
                f"- đọc trang chính thức: bỏ qua ({skipped})" if skipped
                else f"- đọc trang chính thức ({event.get('bytes')} bytes): {urls}"
            )
            _append_content(tool_lines, event)
        elif kind == "llm_response":
            llm_calls += 1
            prompt_tokens += int(event.get("prompt_tokens") or 0)
            completion_tokens += int(event.get("completion_tokens") or 0)
            cost_usd += float(event.get("cost_usd") or 0.0)
            model = str(event.get("model") or "")
            if model and model not in models:
                models.append(model)

    usage = (
        f"Usage: {llm_calls} lượt LLM ({', '.join(models) or '?'}), "
        f"{prompt_tokens} prompt + {completion_tokens} completion tokens, "
        f"~${cost_usd:.4f}."
    )
    if not tool_lines:
        tool_lines = [
            "- KHÔNG có tool call / prefetch nào trong transcript — bước này không mở "
            "nguồn ngoài nào."
        ]
    text = "\n".join([usage, "Tool & nguồn đã mở:"] + tool_lines)
    if len(text) > max_chars:
        text = text[: max(0, max_chars - len(_TRUNCATED_MARK))] + _TRUNCATED_MARK
    return text
