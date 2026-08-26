"""The standing set of briefs the sprint pipeline is measured against.

Chosen so each one can only pass for the right reason:

- `streaming_services` and `note_taking` are the two live v77 benchmarks, kept
  verbatim so an offline run is comparable to the numbers in the report.
- `parenthesised_subjects` is the shape that broke the router in UAT — attributes
  after the colon, subjects inside the parentheses.
- `no_enumeration` has no entity list at all, which must not silently become one
  search per noun.
- `over_cap` lists more entities than even the SCALED prefetch budget allows, and
  exists to prove the cap holds instead of the brief setting the spend.
- `c3_prose` is the v78 C3 brief verbatim — the subjects sit in running prose after
  "của", the one shape that used to resolve to zero entities and lose the blind
  judging to the team pipeline.
- `intake_rephrased` is the goal the INTAKE actually writes for that same brief
  (live task 8251ebc8c8c0, verbatim): deliverable-head ("Tóm tắt ngắn về …"), the
  shape that once produced five queries about the deliverable instead of the price.
- `intake_no_connector` is the intake's SECOND rephrase of the same brief (live task
  847cefe9b088, verbatim): the list lost its "và", the shape the prose parser's
  connector requirement used to reject back to one kitchen-sink query.

`ROUTING_CASES` is a SECOND, disjoint group. The eight above all route the same way
(`sprint`/`heuristic`) because they were chosen to measure what a sprint SPENDS — which
makes them useless for measuring what the ROUTER decides. Every branch a routing report
should be able to see a change in needs at least one brief that takes it, so the routing
group covers the four refusal kinds, both forced prefixes, the multi-ask shape and the
entity cap. They carry no spend budget: nothing runs them through a pipeline.
"""

from __future__ import annotations

from my_crew.bench.pipeline_bench import BriefCase

STREAMING_SERVICES = BriefCase(
    name="streaming_services",
    goal=(
        "So sánh 5 dịch vụ streaming nhạc tại Việt Nam (Spotify, YouTube Music, "
        "Apple Music, Zing MP3, Nhaccuatui): giá gói cá nhân, kho nhạc Việt, "
        "chất lượng âm thanh. Nêu rõ nguồn."
    ),
    acceptance="Đủ 5 dịch vụ × 3 tiêu chí, mỗi mục có nguồn.",
    expected_entities=("Spotify", "YouTube Music", "Apple Music", "Zing MP3", "Nhaccuatui"),
    # 5 subjects buy a (6, 11) scaled budget; the doom test drives this brief through
    # both revise rounds, so its ceiling is the scaled total, not the flat legacy 8.
    max_searches=11,
)

NOTE_TAKING = BriefCase(
    name="note_taking",
    goal=(
        "So sánh 5 công cụ note-taking: Notion, Obsidian, Logseq, Google Keep và "
        "Apple Notes theo giá, khả năng offline, liên kết ghi chú."
    ),
    acceptance="Đủ 5 công cụ × 3 tiêu chí, mỗi mục có nguồn.",
    expected_entities=("Notion", "Obsidian", "Logseq", "Google Keep", "Apple Notes"),
)

PARENTHESISED_SUBJECTS = BriefCase(
    name="parenthesised_subjects",
    goal=(
        "Đánh giá 3 sàn thương mại điện tử (Shopee, Lazada, Tiki): phí sàn, "
        "tốc độ giao, hỗ trợ người bán."
    ),
    expected_entities=("Shopee", "Lazada", "Tiki"),
)

NO_ENUMERATION = BriefCase(
    name="no_enumeration",
    goal="Tóm tắt xu hướng thanh toán không tiền mặt tại Việt Nam năm 2026.",
    expected_entities=(),
    # No entity list means no per-entity fan-out: one overview search is the honest
    # spend, and anything near the cap would mean the router invented subjects.
    max_searches=4,
)

OVER_CAP = BriefCase(
    name="over_cap",
    goal=(
        "So sánh 14 ngân hàng số: Timo, Cake, TNEX, Ubank, Liobank, MBBank, "
        "Techcombank, VPBank, ACB, TPBank, VIB, OCB, MSB và HDBank "
        "theo phí, lãi suất, ứng dụng."
    ),
    # Deliberately no expected_entities: the point is the SPEND cap, not the parse.
    # 14 subjects exceed SCALED_PREFETCH_CAP (12), so the budget — not the brief —
    # decides the spend; the ceiling is SCALED_TOTAL_CAP.
    max_searches=16,
)

C3_PROSE = BriefCase(
    name="c3_prose",
    goal=(
        "Tìm giá gói cá nhân/nhóm nhỏ (hoặc giá cho 5 người) của Notion, Figma, "
        "Obsidian, Canva và Google Workspace theo tháng; xác định công cụ nào đang "
        "có khuyến mãi hoặc gói miễn phí đủ dùng cho nhóm 5 người."
    ),
    acceptance="Đủ 5 công cụ: giá theo tháng, khuyến mãi/gói miễn phí, mỗi mục có nguồn.",
    expected_entities=("Notion", "Figma", "Obsidian", "Canva", "Google Workspace"),
    max_searches=11,
)

INTAKE_REPHRASED = BriefCase(
    name="intake_rephrased",
    goal=(
        "Tóm tắt ngắn về chi phí hàng tháng gói cá nhân hoặc gói nhóm nhỏ hiện nay "
        "của Notion, Figma, Obsidian, Canva và Google Workspace; chỉ ra công cụ nào "
        "đang có chương trình giảm giá hoặc gói miễn phí đủ dùng cho nhóm khoảng 5 "
        "người; đưa nhận định ngắn giữa việc đổi công cụ hay giữ nguyên Notion + Figma"
    ),
    acceptance="Đủ 5 công cụ: giá theo tháng, giảm giá/gói miễn phí, mỗi mục có nguồn.",
    expected_entities=("Notion", "Figma", "Obsidian", "Canva", "Google Workspace"),
    max_searches=11,
)

INTAKE_NO_CONNECTOR = BriefCase(
    name="intake_no_connector",
    goal=(
        "Tóm tắt ngắn chi phí hiện nay của các công cụ Notion, Figma, Obsidian, "
        "Canva, Google Workspace cho nhóm nội dung; so sánh giá gói cá nhân hoặc "
        "gói nhóm nhỏ khoảng 5 người, xác định công cụ nào có chương trình giảm "
        "giá hoặc gói miễn phí đủ dùng, giúp CEO cân nhắc chuyển đổi hay giữ "
        "nguyên hiện tại để"
    ),
    acceptance="Đủ 5 công cụ: giá theo tháng, giảm giá/gói miễn phí, mỗi mục có nguồn.",
    expected_entities=("Notion", "Figma", "Obsidian", "Canva", "Google Workspace"),
    max_searches=11,
)

# --- routing group: one brief per router branch ---------------------------------------

REFUSAL_EXTERNAL_WRITE = BriefCase(
    name="refusal_external_write",
    goal="Tổng hợp báo giá 3 nhà cung cấp rồi gửi email cho khách hàng chốt đơn.",
)

REFUSAL_SHELL = BriefCase(
    name="refusal_shell",
    goal="Clone repo về máy rồi chạy test suite, báo lại kết quả build.",
)

REFUSAL_MULTI_STAFF = BriefCase(
    name="refusal_multi_staff",
    goal="Việc này cần cả đội cùng làm: khảo sát thị trường và dựng bản chào giá.",
)

REFUSAL_LONG_HORIZON = BriefCase(
    name="refusal_long_horizon",
    goal="Xây dựng lộ trình 6 tháng cho mảng nội dung, chia theo từng giai đoạn.",
)

PREFIX_SPRINT = BriefCase(
    name="prefix_sprint",
    goal=(
        "sprint: khảo sát 5 đối thủ chính, viết bản tóm tắt định vị, và dựng kế "
        "hoạch truyền thông 2 tuần tới"
    ),
)

PREFIX_TEAM = BriefCase(
    name="prefix_team",
    goal="team: tóm tắt tin tức ngành xe điện tuần này",
)

MULTI_ASK = BriefCase(
    name="multi_ask",
    goal=(
        "Làm giúp anh mấy việc:\n"
        "- khảo sát 5 đối thủ chính trong mảng giao đồ ăn\n"
        "- viết bản tóm tắt định vị sản phẩm\n"
        "- dựng kế hoạch truyền thông 2 tuần tới"
    ),
)

#: Cùng ba đầu việc của `multi_ask`, viết liền một câu. Cặp này tồn tại để bảng delta
#: nhìn thấy được một lỗi đã xảy ra thật: bản đầu chỉ đếm đánh số ĐẦU DÒNG, nên cách
#: viết liền câu ra sprint còn cách viết xuống dòng ra team — lane phụ thuộc việc CEO
#: có bấm Enter hay không. Giữ cả hai cách viết trong bộ đề thì lần lệch sau lộ ra ở
#: đây thay vì phải chạy live mới thấy.
MULTI_ASK_INLINE = BriefCase(
    name="multi_ask_inline",
    goal=(
        "Làm giúp anh 3 việc: (1) khảo sát 5 đối thủ chính trong mảng giao đồ ăn, "
        "(2) viết bản tóm tắt định vị sản phẩm của mình, "
        "(3) dựng kế hoạch truyền thông 2 tuần tới."
    ),
)

ROUTING_CASES = (
    REFUSAL_EXTERNAL_WRITE,
    REFUSAL_SHELL,
    REFUSAL_MULTI_STAFF,
    REFUSAL_LONG_HORIZON,
    PREFIX_SPRINT,
    PREFIX_TEAM,
    MULTI_ASK,
    MULTI_ASK_INLINE,
    OVER_CAP,
)

ALL_CASES = (
    STREAMING_SERVICES,
    NOTE_TAKING,
    PARENTHESISED_SUBJECTS,
    NO_ENUMERATION,
    OVER_CAP,
    C3_PROSE,
    INTAKE_REPHRASED,
    INTAKE_NO_CONNECTOR,
)
