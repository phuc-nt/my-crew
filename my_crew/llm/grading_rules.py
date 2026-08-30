"""Evidence rules shared by both graders of a step's result.

A step's result is graded twice by the same rubric: the worker's own `self_check`
(`team_task_check_prompt.build_self_check_messages`) and a colleague's peer `review`
(`team_task_prompt.build_review_messages`). Peer review re-grades the SAME acceptance
criteria through a stranger's eyes — a different reader, not a different bar.

The two prompts used to carry their own copies of these rules and drifted apart:
peer review was missing the countable-requirement rule and the original-ask ceiling,
so it would pass a result whose criteria demanded a URL when the text merely said
"nguồn: X", and it would fail a result for missing something the CEO never asked for.
Both are the failure modes those rules exist to prevent, and self-check caught them
while review did not. Keeping the rules in one constant is what makes "the same bar"
true by construction instead of by two authors remembering to edit both files.

What stays in each caller's own prompt: the role framing (who you are and whose work
this is) and the JSON output contract, which genuinely differ — self-check reports a
`confidence`, peer review reports `notes` and is explicitly denied any channel beyond
the verdict. Those are not duplication; these rules were.
"""

from __future__ import annotations

#: The result must trace back to what the step was actually given. Stated first and
#: marked as taking precedence because a fabricated figure otherwise satisfies every
#: other criterion — a well-formed invention is indistinguishable from sourced work
#: unless the grader is told to check provenance before form.
SOURCE_RULE = (
    "QUY TẮC NGUỒN (bắt buộc, xét TRƯỚC mọi tiêu chí khác): nếu có khối ĐẦU VÀO, đối "
    "chiếu mọi số liệu, tên nguồn và trích dẫn trong kết quả với đầu vào đó. Kết quả "
    "KHÔNG được chứa số liệu hay tên tổ chức không truy được về đầu vào. Đặc biệt: nếu "
    "đầu vào ghi 'KHÔNG CÓ KẾT QUẢ' / bước trước bị bỏ qua, thì mọi bảng số, khoảng giá "
    "hay tên nguồn trong kết quả đều là bịa — chấm `passed=false` và nêu rõ ở `failures`, "
    "kể cả khi kết quả trình bày đủ mọi mục tiêu chí (trừ số liệu truy được về khối "
    "'BẢN NHÁP CHƯA ĐẠT SOÁT' đính kèm ngay dưới placeholder đó — xem QUY TẮC KHOẢNG "
    "TRỐNG THỪA KẾ). Ngược lại, dữ liệu MỚI HƠN kiến "
    "thức của bạn KHÔNG phải bằng chứng bịa: chỉ kết luận bịa khi đầu vào cho thấy KHÔNG "
    "hề có dữ liệu đó. Kết quả trung thực khi thiếu dữ liệu phải NÓI RÕ là thiếu, không "
    "lấp bằng ước lượng nghe hợp lý."
)

#: Criteria that can be counted must actually be counted. Without this a grader marks
#: "có link nguồn" as met because the prose says "nguồn: X" — it grades the claim of
#: compliance rather than the compliance.
COUNTABLE_RULE = (
    "QUY TẮC ĐẾM ĐƯỢC: tiêu chí nêu yêu cầu đếm được (kèm link/URL, đủ N mục, có bảng, "
    "có mục nguồn) thì phải KIỂM THẬT trong kết quả — tiêu chí đòi link/URL mà kết quả "
    "không có chuỗi 'http' nào là KHÔNG ĐẠT, dù phần chữ có ghi 'nguồn: X'; đòi N mục "
    "thì đếm đủ N. Không chấm đạt theo cảm giác."
)

#: "Official" is a claim about where a number came from, not a compliment. Only a
#: contradiction counts: naming a source secondary is honest reporting, not a defect.
SOURCE_LABEL_RULE = (
    "QUY TẮC NHÃN NGUỒN: kết quả gán nhãn 'trang chính thức' / 'nguồn chính thức' cho "
    "một số liệu thì nhãn đó phải khớp nguồn THẬT của số — trang của chính hãng/nhà cung "
    "cấp dịch vụ đó. Số lấy từ báo, blog, đại lý, trang tổng hợp là nguồn THỨ CẤP: ghi "
    "kèm vẫn tốt, nhưng gọi nó là 'chính thức' là sai nhãn ⇒ nêu ở `failures`. Chỉ chấm "
    "khi nhãn MÂU THUẪN với nguồn thấy được; không có gì để đối chiếu thì bỏ qua, và bản "
    "ghi rõ 'nguồn thứ cấp' / 'chưa có nguồn chính thức' là TRUNG THỰC, không phải lỗi — "
    "kể cả khi trang chính thức đã được mở nhưng không trả về số nào."
)

#: Acceptance criteria are generated from the CEO's ask, so they can overshoot it.
#: Grading against the inflated criterion punishes a result that did exactly what was
#: asked; the original request is the ceiling, not the floor.
REQUEST_CEILING_RULE = (
    "QUY TẮC TRẦN YÊU CẦU: nếu ĐẦU VÀO có khối 'YÊU CẦU GỐC CỦA CEO' thì yêu cầu đó là "
    "TRẦN — tiêu chí nào đòi CAO HƠN đề gốc (vd đề chỉ đòi 'link nguồn' mà tiêu chí đòi "
    "'nguồn chính thức của hãng'; đề cho phép ghi THIẾU mà tiêu chí bắt phải có đủ số) "
    "thì chấm theo ĐỀ GỐC, không theo phần thổi phồng. Kết quả trung thực dùng nguồn gần "
    "kề + ghi rõ THIẾU cho phần không tìm được là ĐẠT với đề như vậy."
)

#: A cell that honestly reports "not public" with a trace of the attempted lookup is
#: finished work, not a gap. Without this rule a grid brief whose data is partly
#: unpublished ("liên hệ bán hàng" pricing) can never pass any grader — measured on
#: live grid briefs: both lanes 0/6 completions, with the honest partial answer
#: produced and then failed precisely for being honest.
NONPUBLIC_RULE = (
    "QUY TẮC DỮ LIỆU KHÔNG CÔNG KHAI: một ô/mục ghi rõ 'không công khai' hay 'không "
    "tìm thấy công bố' KÈM dấu vết đã tra (tên trang/nguồn đã kiểm, vd 'trang giá "
    "chính thức ghi liên hệ bán hàng') là ô ĐÃ HOÀN THÀNH — chấm ĐẠT cho ô đó kể cả "
    "khi tiêu chí đòi con số hay nguồn từng ô; ghi chú đó CHÍNH LÀ nguồn của ô. Chỉ "
    "chấm KHÔNG ĐẠT khi ô bỏ trống, ghi thiếu mà không nói đã tra ở đâu, hoặc dữ "
    "liệu đó thật ra có sẵn trong ĐẦU VÀO."
)

#: A step downstream of a deliberately dropped step must not be failed for the gap it
#: inherited. Both graders used to carry their own verbatim copies of this rule (the
#: exact drift this module exists to prevent). The draft clause exists because a drop
#: can now carry the dead step's last failed draft (`ops_stalled_task.py`'s
#: SALVAGE_DRAFT_PREFIX): the draft rides inside the step's input, so labeled use of
#: it IS traceable sourcing — without this clause the SOURCE_RULE placeholder sentence
#: would fail every honest consumer of a salvaged draft.
INHERITED_GAP_RULE = (
    "QUY TẮC KHOẢNG TRỐNG THỪA KẾ: nếu ĐẦU VÀO bước này ghi 'KHÔNG CÓ KẾT QUẢ' "
    "(bước trước đã bị chủ động bỏ qua) và kết quả ĐÃ nêu trung thực phần thiếu dữ "
    "liệu đó, thì các tiêu chí phụ thuộc dữ liệu bị thiếu KHÔNG tính là không đạt — "
    "chấm trên phần dữ liệu thật sự có; khoảng trống được ghi rõ là trung thực, "
    "không phải lỗi. Riêng khi placeholder đó kèm khối 'BẢN NHÁP CHƯA ĐẠT SOÁT': kết "
    "quả ĐƯỢC dùng nội dung nháp, miễn là dán nhãn 'dữ liệu chưa qua soát' cạnh số "
    "liệu/kết luận lấy từ nháp — dùng nháp CÓ nhãn không phải bịa, không phải lỗi; "
    "chỉ chấm không đạt khi kết quả lấy số từ nháp mà KHÔNG dán nhãn, hoặc thêm dữ "
    "liệu ngoài những gì nháp đã ghi."
)

#: The whole evidence bar, in the order a grader should apply it: provenance first,
#: then the checks that keep it from grading prose instead of substance.
EVIDENCE_RULES = " ".join(
    (SOURCE_RULE, COUNTABLE_RULE, SOURCE_LABEL_RULE, REQUEST_CEILING_RULE,
     NONPUBLIC_RULE)
)
