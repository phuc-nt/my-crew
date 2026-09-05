"""The aggregate-role prompt: one CEO-facing Vietnamese summary of a finished team task.

Lives here rather than inline in `team_tick_collaborators.make_aggregate` so the role
bench (`my_crew.bench.role_bench_probes`) can send the SAME text the ticker sends. A
probe that paraphrased the prompt would measure the paraphrase.

The rules baked into the prompt each answer a production incident:
- "Bắt đầu NGAY bằng bản tóm tắt": some models (observed: qwen3.7-plus) write an English
  chain-of-thought preamble into content; Telegram then truncates at 4096 chars and the
  CEO receives ONLY the preamble — the actual Vietnamese summary is cut off entirely.
- "QUY TẮC TRUNG THỰC": a step that delivered nothing must be reported as missing, never
  papered over with invented numbers.
- The "soát chéo KHÔNG đạt" tail: the "Soát chéo chưa đạt" header above the summary is
  code-built; without this note the summarizer — which never sees failed review rows —
  could write an unqualified "hoàn thành tốt đẹp" right beneath it.
"""

from __future__ import annotations

from collections.abc import Iterable

#: The summary must fit one Telegram message with room for the code-built headers.
SUMMARY_MAX_CHARS = 3000


def build_team_summary_prompt(
    task_title: str, wrapped_parts: Iterable[str], unresolved_notes: Iterable[str] = (),
) -> str:
    """`wrapped_parts`: one already-wrapped block per step (`format_internal_content`).
    `unresolved_notes`: the failed-review lines, one per step, when review ran out of
    rework rounds; empty ⇒ no tail."""
    prompt = (
        f"Tóm tắt ngắn gọn (tiếng Việt) kết quả của việc '{task_title}' cho "
        "CEO, dựa trên các bước sau. QUY TẮC TRUNG THỰC: bước nào ghi 'KHÔNG "
        "CÓ KẾT QUẢ'/bị bỏ qua thì phải nêu rõ là thiếu dữ liệu — tuyệt đối "
        "không suy diễn hay bịa số liệu thay cho bước đó. ĐỊNH DẠNG: bắt đầu "
        f"câu trả lời NGAY bằng bản tóm tắt tiếng Việt hoàn chỉnh, dưới {SUMMARY_MAX_CHARS} "
        "ký tự; KHÔNG viết quá trình suy nghĩ, không lời dẫn, không phân tích "
        "meta, không tiếng Anh.\n\n"
        + "\n\n".join(wrapped_parts)
    )
    notes = [n for n in unresolved_notes if n]
    if notes:
        prompt += (
            "\n\nLƯU Ý: soát chéo KHÔNG đạt và đã hết lượt sửa — "
            + "; ".join(notes)
            + ". Bản tóm tắt phải thừa nhận các điểm này, không được "
            "khẳng định mọi thứ đều ổn."
        )
    return prompt
