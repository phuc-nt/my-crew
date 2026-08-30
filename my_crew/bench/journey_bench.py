"""Chốt số đo của các journey live để bản sau so được với bản này.

Journey chạy qua model thật, tiến trình thật, HTTP thật — nên KHÔNG có hai lượt nào
giống hệt nhau. Đó là điểm khác căn bản so với `routing_bench`: ở đó so bằng `!=` là
đúng, vì bộ định tuyến thuần luật và mọi lệch đều là tín hiệu. Ở đây so bằng `!=` sẽ
kêu ở MỌI lượt chạy — cost lệch vài phần nghìn đô, wall lệch vài giây — và một bảng
delta lúc nào cũng đỏ thì không ai đọc nữa. Bảng đó tệ hơn là không có bảng.

Nên mỗi trục ở đây khai báo cách so của riêng nó:

- **Trục rời rạc** (`terminal_state`, `lane`) so bằng `!=`. Một journey đổi từ `done`
  sang `stalled` là hồi quy dù chỉ một lần, không có "dung sai" nào hợp lý ở đây.
- **Trục liên tục** (`cost_usd`, `wall_s`) so theo NGƯỠNG TƯƠNG ĐỐI. Chỉ báo khi lệch
  vượt biên, vì dưới biên là nhiễu model chứ không phải thay đổi hành vi.
- **Trục đếm** (`llm_calls`) cũng theo ngưỡng, nhưng chặt hơn: số lời gọi nhảy vọt là
  dấu hiệu vòng lặp thừa, thứ đáng báo sớm hơn là tiền.

Ngưỡng đặt rộng có chủ đích. Mục tiêu của mode này là bắt HỒI QUY THẬT (một bản làm
journey đắt gấp rưỡi, hoặc chết ở trạng thái khác), không phải đo dao động vi mô. Một
ngưỡng chặt quá sẽ sinh báo động giả, và báo động giả làm người ta bỏ qua cả báo thật.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

#: Bản của định dạng JSON mode này ghi ra. `compare_journey` từ chối so hai bản lệch
#: nhau — im lặng so nhầm hai định dạng còn tệ hơn là không so được.
FORMAT_VERSION = 1

#: Lệch tương đối tối đa coi là nhiễu, theo trục. Vượt mức này mới thành một dòng delta.
#: `llm_calls` chặt hơn tiền và thời gian vì một vòng lặp thừa hiện ra ở số lời gọi
#: TRƯỚC khi nó đủ lớn để lộ ra ở hoá đơn.
TOLERANCE = {
    "cost_usd": 0.50,   # +50%: đắt gấp rưỡi là hồi quy, dao động 10-20% là chuyện thường
    # Thời gian nhiễu nhất, và ĐO ĐƯỢC là nhiễu tới đâu: hai lượt chạy CÙNG một bản
    # 0.15.0 cho j2 lệch -62% (87.8s -> 33.4s) thuần do tải phía nhà cung cấp model.
    # Ngưỡng 0.60 ban đầu đặt bằng phỏng đoán nên đã kêu ngay ở phép đo thật đầu tiên.
    # 1.20 để một dòng wall_s nghĩa là "chậm gấp đôi", thứ đáng đọc — chứ không phải
    # "hôm nay provider bận", thứ dạy người ta bỏ qua cả bảng.
    "wall_s": 1.20,
    "llm_calls": 0.35,
}

#: Trục so bằng `!=`, không dung sai.
EXACT_FIELDS = ("terminal_state",)

#: Sàn tuyệt đối cho trục tiền. Dưới ngưỡng này, lệch tương đối vô nghĩa: $0.0001 so với
#: $0.0002 là "gấp đôi" nhưng chẳng nói lên điều gì ngoài việc cả hai đều ~0. Không có
#: sàn thì mọi journey rẻ đều báo động giả vĩnh viễn.
COST_FLOOR_USD = 0.002


@dataclass(frozen=True)
class JourneyMetric:
    """Một journey chạy xong để lại gì.

    Cùng bộ khoá mà `journey_budget` in ra cuối mỗi case (`cost_usd`, `wall_s`) cộng
    thêm trạng thái kết thúc và phân bố lane — cố ý: cái chốt vào baseline và cái đọc
    được từ output của test phải nói cùng một thứ tiếng thì mới đối chiếu tay được.
    """

    journey: str
    cost_usd: float
    wall_s: float
    llm_calls: int
    #: `done` / `stalled` / `failed` — trục rời rạc, đổi là hồi quy.
    terminal_state: str
    #: lane -> số bước, ví dụ `{"sprint": 1}`. So theo tập khoá chứ không theo số đếm:
    #: xem `compare_journey`.
    lanes: dict[str, int]


def _relative_delta(base: float, cand: float, *, floor: float = 0.0) -> float | None:
    """Lệch tương đối, hoặc None khi cả hai bên đều dưới sàn (so sánh vô nghĩa).

    Mẫu số là `base`; `base == 0` mà `cand > 0` là thay đổi vô hạn về tỉ lệ nên trả về
    một số lớn thay vì chia cho không.
    """
    if abs(base) < floor and abs(cand) < floor:
        return None
    if base == 0:
        return 0.0 if cand == 0 else float("inf")
    return (cand - base) / abs(base)


def make_metric(journey: str, *, cost_usd: float, wall_s: float, llm_calls: int,
                terminal_state: str, lanes: dict[str, int] | None = None) -> JourneyMetric:
    return JourneyMetric(
        journey=journey,
        cost_usd=round(float(cost_usd), 6),
        wall_s=round(float(wall_s), 1),
        llm_calls=int(llm_calls),
        terminal_state=str(terminal_state),
        lanes=dict(lanes or {}),
    )


def build_baseline(metrics: list[JourneyMetric], *, version: str) -> dict[str, Any]:
    """Gói các số đo thành baseline commit được vào repo.

    `version` đi kèm để đọc lại còn biết số này chốt ở bản nào — một file baseline không
    ghi bản của chính nó thì sau vài tháng không ai dám tin nữa.
    """
    return {
        "format_version": FORMAT_VERSION,
        "version": version,
        "journeys": {m.journey: asdict(m) for m in metrics},
    }


def compare_journey(baseline: dict[str, Any],
                    candidate: dict[str, Any]) -> list[dict[str, Any]]:
    """Chỉ những trục LỆCH QUÁ NGƯỠNG, phẳng, sẵn sàng in ra bảng.

    Từ chối so hai định dạng lệch bản, theo tiền lệ `compare_routing`: một danh sách
    khác biệt sinh ra do đổi định dạng trông hệt như thay đổi hành vi.
    """
    b_ver = baseline.get("format_version", 0)
    c_ver = candidate.get("format_version", 0)
    if b_ver != c_ver:
        raise ValueError(
            f"journey report format_version lệch nhau ({b_ver} vs {c_ver}) — "
            "chạy lại baseline bằng bản script hiện tại trước khi so"
        )

    rows: list[dict[str, Any]] = []
    b_j = baseline.get("journeys", {})
    c_j = candidate.get("journeys", {})
    for name in sorted(set(b_j) | set(c_j)):
        b = b_j.get(name)
        c = c_j.get(name)
        if b is None or c is None:
            rows.append({"case": name, "field": "journey",
                         "baseline": "—" if b is None else "có",
                         "candidate": "—" if c is None else "có",
                         "delta": ""})
            continue

        for field in EXACT_FIELDS:
            if b.get(field) != c.get(field):
                rows.append({"case": name, "field": field,
                             "baseline": b.get(field), "candidate": c.get(field),
                             "delta": "đổi"})

        # Lane so theo TẬP KHOÁ, không theo số đếm: một journey chạy thêm/bớt một bước
        # trong cùng lane là dao động bình thường của model, còn việc nó bắt đầu dùng
        # một lane KHÁC là thay đổi kiến trúc định tuyến — chỉ vế sau đáng báo.
        b_lanes = set((b.get("lanes") or {}).keys())
        c_lanes = set((c.get("lanes") or {}).keys())
        if b_lanes != c_lanes:
            rows.append({"case": name, "field": "lanes",
                         "baseline": sorted(b_lanes), "candidate": sorted(c_lanes),
                         "delta": "đổi"})

        for field, tol in TOLERANCE.items():
            floor = COST_FLOOR_USD if field == "cost_usd" else 0.0
            delta = _relative_delta(float(b.get(field) or 0.0),
                                    float(c.get(field) or 0.0), floor=floor)
            if delta is None:
                continue
            if abs(delta) > tol:
                rows.append({"case": name, "field": field,
                             "baseline": b.get(field), "candidate": c.get(field),
                             "delta": f"{delta:+.0%}"})
    return rows
