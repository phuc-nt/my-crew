# Viết một domain-pack

> Cách thêm một "nghề" mới (admin/hr/marketer/researcher…) vào harness mà KHÔNG sửa lõi `my_crew/`.
> Đây là một trong 3 ổ cắm community (skill = agentskills.io · tool = MCP · **domain = pack**).
> Aspirational: harness hướng tới cộng đồng; hiện `_template-pack` + doc này là bộ khung, chưa
> có quy trình governance duyệt pack ngoài (xem §An toàn).

## 1. Một pack là gì

Mỗi nghề = 1 thư mục `domain-packs/<tên>-pack/` theo hình dạng **đọc → phân tích → soạn →
(duyệt) → hành động**. Lõi (`my_crew/`) không chứa logic nghề; pack đóng góp qua các module cố định.
hr-pack đã chứng minh: thêm pack = `git diff my_crew/` rỗng (M6 gate) — kể cả khi mang adapter mới
(Google Sheets) lõi chưa từng biết.

## 2. Cấu trúc (copy từ `_template-pack/`)

```
domain-packs/<tên>-pack/
  pack.yaml           # manifest: id, name, report_kinds, servers (allowlist)
  graphs.py           # REPORT_KINDS: {kind → builder}  — bắt buộc
  tools.py            # TOOL_PROVIDER (read seam) — None nếu pack read-only
  write_handlers.py   # ALLOWLIST: {server → (write tool names,)} — {} nếu không ghi
  prompts/            # (tùy chọn) system-prompt .md
  skills/             # (tùy chọn) skill .md (flat hoặc <slug>/SKILL.md agentskills.io)
```

Bắt đầu: `cp -r domain-packs/_template-pack domain-packs/<tên>-pack`, sửa `id` trong pack.yaml,
đổi tên report kind. `_template-pack` (tiền tố `_`) bị loại khỏi discovery nên không chạy nhầm.

## 3. Builder contract (graphs.py)

Mỗi report kind là một builder chữ ký ĐỒNG NHẤT để lõi gọi mọi kind như nhau:

```python
def build(checkpointer, *, config, settings, context, audience, store, remember, tools=None):
    from src.agent.report_graph import build_report_graph   # hoặc graph riêng của bạn
    return build_report_graph(checkpointer, config=config, settings=settings, context=context,
                              report_kind="daily", audience=audience, store=store,
                              remember=remember, tools=tools)

REPORT_KINDS = {"example": build}
```

Graph riêng: xem `hr-pack/graphs.py` (perceive→analyze→compose→deliver + analyzer mới).

## 4. Đọc dữ liệu (tools.py)

`TOOL_PROVIDER` = provider conform `src.packs.tool_provider.ToolProvider` (đọc source → trả
record chuẩn hoá; transport ẩn bên trong). Read-only pack có thể để `None`. Muốn MCP server mới,
xem §6.

## 5. Ghi ra ngoài (write_handlers.py) — LUÔN qua Action Gateway

`ALLOWLIST = {server: (tool_names,)}` đóng góp vào allowlist **default-DENY** của gateway. Pack
CHỈ nới allowlist, KHÔNG bao giờ vượt Lớp A (hard-deny data-loss/credential/security vẫn core-
guarded). Mọi mutation đi qua `ActionGateway` — pack không gọi write API trực tiếp.

## 6. MCP server do pack khai (an toàn — spawn gate)

Pack có thể khai MCP server riêng. NHƯNG một MCP server = spawn `node <dist>` với môi trường —
nên **spawn gate** (`my_crew/packs/pack_mcp_gate.py`) áp default-DENY:

- `mcp_dist` phải là **absolute path** (không cho tương đối trỏ vào thư mục pack);
- phải nằm trong allowlist operator `PACK_MCP_ALLOWED_DIST` (`:`-phân tách) — **rỗng = từ chối tất**;
- subprocess nhận **env đã scrub** (chỉ PATH/HOME + `required_env` khai rõ) — KHÔNG kế thừa token.

Profile-level `integrations:` (operator tự viết profile mình) KHÔNG qua gate này — operator được
tin; pack bên thứ ba thì không.

## 7. Skill của pack (tùy chọn)

`skills/*.md` (flat) hoặc `skills/<slug>/SKILL.md` (agentskills.io). Pack skill = repo-vetted →
inject raw. Skill copy từ community vào `profiles/<id>/skills/` = untrusted tier → tự động wrap.

## 8. Test pack

- `PackRegistry().load("<tên>")` load được; `report_kinds` đúng.
- `git diff my_crew/` rỗng cho phần report-kind (M6 gate). *Lưu ý:* nếu pack cần MCP server mới qua
  spawn-gate hoặc field pack.yaml mới, đó là core change RIÊNG — commit tách, không gộp vào
  bằng chứng `git diff my_crew/=∅`.

## An toàn (đọc trước khi nhận pack ngoài)

Cơ chế đã có: allowlist default-deny (tool ghi) + spawn gate (MCP binary) + skill wrap
(untrusted body). **Chưa có** quy trình governance (ai duyệt pack người lạ) — hiện single-user
self-host nên operator tự chịu trách nhiệm pack mình cài. Nhận pack ngoài: đọc `write_handlers.py`
(nó xin ghi gì), `pack.yaml` `mcp_servers` (nó spawn binary gì), skill body — trước khi bật.
