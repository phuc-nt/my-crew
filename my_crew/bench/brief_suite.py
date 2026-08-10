"""The standing set of briefs the sprint pipeline is measured against.

Chosen so each one can only pass for the right reason:

- `streaming_services` and `note_taking` are the two live v77 benchmarks, kept
  verbatim so an offline run is comparable to the numbers in the report.
- `parenthesised_subjects` is the shape that broke the router in UAT — attributes
  after the colon, subjects inside the parentheses.
- `no_enumeration` has no entity list at all, which must not silently become one
  search per noun.
- `over_cap` lists more entities than the prefetch budget allows, and exists to prove
  the cap holds instead of the brief setting the spend.
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
        "So sánh 9 ngân hàng số: Timo, Cake, TNEX, Ubank, Liobank, MBBank, "
        "Techcombank, VPBank và ACB theo phí, lãi suất, ứng dụng."
    ),
    # Deliberately no expected_entities: the point is the SPEND cap, not the parse.
    max_searches=8,
)

ALL_CASES = (
    STREAMING_SERVICES,
    NOTE_TAKING,
    PARENTHESISED_SUBJECTS,
    NO_ENUMERATION,
    OVER_CAP,
)
