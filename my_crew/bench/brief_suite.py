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
