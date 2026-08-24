# omp/Pi emulation: advisor sweep, prompt audit, role models, provider registry
2026-08-24 · ✅ Done (4/4 phase)

Plan `plans/260824-1057-omp-pi-advisor-and-providers/` — 4 đề xuất được chọn từ
report nghiên cứu omp/Pi. Hai đề xuất bị loại từ đầu (context promotion,
REVIEW.md-per-fleet: chờ đau thật; TUI/lego: bỏ).

## Làm gì

- **Advisor sweep** (P1): "cặp mắt thứ hai" rẻ, đọc delta step-transcript của bước
  đang chạy, chèn `nit` (ghi chú office) / `concern` (hướng dẫn bước) mà không cắt
  ngang agent chính. Chạy trong `run_team_tick`, tối đa 1 note/task/sweep, advisor
  hỏng không bao giờ làm hỏng tick. Mặc định TẮT.
- **Prompt audit** (P2): đo 94 call thật từ event `llm_request` trong 37 transcript
  `.data/` — không ước lượng. Kết quả ngược kỳ vọng, xem bên dưới.
- **role_models per-agent** (P3): cơ chế đã có từ v79; phase này khoá bằng test,
  viết docs, và đưa lên form cấu hình web (textarea `role = model`) + toggle advisor.
- **Provider registry** (P4): entry trong model chain có thể chỉ định endpoint
  OpenAI-compatible khác OpenRouter bằng tiền tố `provider::model`. Khai báo
  `providers: {name: {base_url, api_key_env}}` — chỉ TÊN biến môi trường vào yaml,
  không bao giờ là key.

## Quyết định & vì sao

| Quyết định | Vì sao | Đánh đổi |
|---|---|---|
| Advisor sweep-based, không cắt ngang lượt | my-crew là fleet tick bất đồng bộ, không có vòng lặp lượt tương tác như omp | Mất khả năng lái giữa chừng; bù lại không bao giờ làm hỏng bước đang chạy |
| `::` làm dấu tách provider | id OpenRouter đã dùng `/` (org/model) và `:` (hậu tố `:free`) | Cú pháp lạ mắt, nhưng là ký tự duy nhất còn trống |
| Chỉ lưu `api_key_env`, không lưu key | yaml chứa registry vẫn an toàn để đọc/chia sẻ | Thêm một lớp gián tiếp khi cấu hình |
| `role_models` ghi đè NGUYÊN KHỐI, không merge lá | role bị xoá khỏi form phải biến mất khỏi yaml thật; merge lá sẽ để override cũ nằm lại và **âm thầm tính tiền tiếp** | Không sửa được một role lẻ mà không gửi cả map |
| GET cố tình KHÔNG trộn env vào payload | hiện giá trị kế thừa từ fleet trong ô sửa được sẽ khiến một lần Save vô hại ghim luôn giá trị đó vào yaml riêng của agent | Form không cho thấy giá trị đang thực sự có hiệu lực |
| Không dùng provider OAuth thuê bao | fleet chạy 24/7 trên subscription cá nhân = vùng xám ToS | Chỉ hỗ trợ provider có API key |

## Vấp & học được

- **Prompt audit tìm ra lỗi đúng-sai, không phải chỗ béo.** Diff hai grader
  (`difflib` 0.615) cho thấy chúng đã **trôi khỏi nhau**: peer review thiếu 2 trong
  4 quy tắc bằng chứng mà self-check có — nên nó sẽ *pass* kết quả thiếu URL và
  *fail* kết quả không đạt tiêu chí khắt khe hơn cả điều CEO hỏi. Gộp về một hằng
  `EVIDENCE_RULES`. Prompt **to ra** (+782 / +372 chars) chứ không giảm 30% như
  phase nhắm. Trả lại 2 quy tắc thiếu đáng giá hơn số token tiết kiệm được.
  Bài học: đo trước rồi hãy cắt — chỗ mình đoán là mỡ hoá ra là xương.
- **Seam test dịch chỗ thì phải sửa test, không phải né.** Tiêu chí phase ghi "test
  client cũ giữ nguyên"; nhưng `_openai()` thành `_client_for(provider)` là seam
  dịch thật. Vá 4 điểm monkeypatch là sửa trung thực nhất — tiêu chí đó nói về
  *hành vi* tương đương, không phải nguyên văn dòng test.
- **Endpoint đoán mò tốn 20 vòng poll.** `GET /api/team/tasks/<id>` 404; task vẫn
  chạy thật. Artifact nằm ở `.data/artifacts/team-tasks/<id>/`, còn transcript lại
  ở `.data/agents/<agent>/artifacts/team-tasks/<id>/transcripts/` — đọc
  `step_recorder.py` ra ngay, đáng lẽ đọc trước khi poll.
- **Console error "sai" có khi là test đang chạy đúng.** Live spec assert 0 console
  error, nhưng bước 1 cố tình gửi payload để backend từ chối → browser log 400. Lọc
  đúng cái 400 đó thay vì nới assertion.
- Test đầu bám nhầm nhãn (`Model theo vai` thay vì `Model theo loại việc`) và đoán
  cú pháp `key: value` trong khi form dùng `key = value` — đọc spec đang xanh sẵn
  nhanh hơn đoán.

## Kiểm chứng thật

Fleet thật chạy task thật `b34ebc3db8b4` trên `analyst`: chỉ role `content` đi qua
provider registry, `plan`/`review`/`util` vẫn OpenRouter — đúng 3 tầng config:

```
req  role=plan    chain=['deepseek/deepseek-v4-pro-0813']
resp model=deepseek/deepseek-v4-pro-0813            cost=0.0040062
req  role=content chain=['altroute::deepseek/deepseek-v4-pro-0813', 'deepseek/...']
resp model=altroute::deepseek/deepseek-v4-pro-0813  cost=0.0091146
```

Fallback xuyên provider cũng thử thật: entry `deadend::` ăn 400 thật từ endpoint
sống → chain đi tiếp → `fallback_from` giữ nguyên entry có tiền tố để còn quy được
chi phí. Browser thật (chromium, backend sống): 3 live spec xanh, `::` sống sót
trọn vòng textarea → PATCH → yaml → GET. Zero-migration xác nhận: không khai
`providers:` thì mọi agent resolve y hệt trước v91.

Cổng cuối: 3785 BE (+36) / 1 skipped, 417 FE / 59 file, `tsc -b` + ruff sạch.
Commit `43edfa4`.

## Mở / sang sau

- Advisor mặc định TẮT; cần một vòng UAT quan sát cost/chất lượng tín hiệu trước
  khi tính chuyện bật mặc định hoặc thêm bậc `blocker`/pause.
- `role=(unlabeled)` — 6 call, payload user-message lớn nhất mọi role (avg 15,198
  chars) mà chưa truy ra builder nào phát ra.
- Registry mới chỉ hỗ trợ endpoint OpenAI-compatible; vendor có API riêng vẫn phải
  đi qua OpenRouter.
