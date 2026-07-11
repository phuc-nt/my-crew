# Hướng dẫn tích hợp Firecrawl (self-host Docker local) vào MPM

**Ngày:** 2026-07-11 · **Loại:** hướng dẫn tích hợp (không phải plan cook).
**Bối cảnh:** đã dựng Firecrawl self-host qua Docker Compose trên máy Mac (arm64) — endpoint `http://localhost:3002`, no-auth (`USE_DB_AUTHENTICATION=false`). Tài liệu này chỉ cách MPM gọi nó để có năng lực **web scrape/crawl** (đọc nội dung URL ra markdown sạch, kể cả site JS-heavy/chống bot).

**⚠️ Đọc mục §4 (an toàn) TRƯỚC khi code** — Firecrawl là năng lực MPM cố tình CHƯA có, tích hợp phải giữ invariant.

---

## 0. Firecrawl local — thông số cố định

| | |
|---|---|
| Endpoint | `http://localhost:3002` (loopback, private) |
| Auth | none (self-host `USE_DB_AUTHENTICATION=false`) — apiKey bất kỳ đều qua |
| Repo/compose | `~/workspace/firecrawl` (docker compose, 6 service, auto-restart `unless-stopped`) |
| Bật/tắt | `cd ~/workspace/firecrawl && docker compose up -d` / `down` |
| Kiểm sống | `curl -s -o /dev/null -w "%{http_code}" http://localhost:3002/` → `200` |

**API dùng đến (đã verify shape thật):**
```
POST /v1/scrape   {"url":"...","formats":["markdown"]}
  → {"success":true,"data":{"markdown":"...","metadata":{"title","statusCode","sourceURL",...}}}

POST /v1/search   {"query":"...","limit":N}
  → {"success":true,"data":[...],"id":"..."}
```

---

## 1. Firecrawl khác gì `web_search_tool.py` hiện có (đọc kỹ)

MPM đã có `src/tools/web_search_tool.py` nhưng nó **cố ý snippets-only** — chú thích trong file: *"NEVER a follow-up GET to any result URL … fetching a result page is a categorically different, and much [riskier] operation"* (4-layer injection defense, redact query). Đó là **search**, KHÔNG phải **fetch nội dung trang**.

**Firecrawl bổ sung đúng cái MPM tránh:** lấy TOÀN BỘ nội dung 1 URL. Vì đây là năng lực mới + rủi ro cao hơn (nội dung web không tin được → prompt-injection), tích hợp phải **thêm tool riêng có guardrail**, KHÔNG nới `web_search_tool` thành fetch.

---

## 2. Convention MPM phải tuân (để code khớp codebase)

1. **HTTP = stdlib `urllib.request`**, KHÔNG thêm `httpx`/`requests`/SDK. (Xem `web_search_tool.py` header: "Stdlib-only HTTP … matching the codebase's established convention". 2 REST call đơn giản không đáng thêm dep.)
2. **Credential env-only** — `ToolProvider` docstring: creds "resolved env-only (`token_env`), never passed through the core". Firecrawl base URL + (dummy) key đọc từ env/settings, không hardcode.
3. **Reader qua pack `ToolProvider`** nếu dùng trong graph; hoặc **tool độc lập** nếu là agent-callable. Core không inspect transport.
4. **Không secret plaintext** — dù key Firecrawl là giả (self-host no-auth), vẫn đặt qua settings/env cho nhất quán.

---

## 3. Hai cách tích hợp (chọn theo nhu cầu)

### Cách A — Module `firecrawl_tool.py` (khuyến nghị, dùng lại được)

Tạo `src/tools/firecrawl_tool.py` — 1 hàm `scrape_url()` stdlib-only, trả markdown + metadata. Đây là mẫu bám convention `web_search_tool.py`:

```python
"""Firecrawl scrape — fetch a URL's full content as markdown via the local
self-hosted Firecrawl (http://localhost:3002). Stdlib-only HTTP, matching the
web_search_tool convention. READ-only: it fetches, never writes."""
from __future__ import annotations
import json, urllib.request
from dataclasses import dataclass

_TIMEOUT_S = 60

@dataclass(frozen=True)
class FirecrawlConfig:
    base_url: str            # e.g. http://localhost:3002 (env: FIRECRAWL_BASE_URL)
    api_key: str | None      # self-host no-auth → any/dummy (env: FIRECRAWL_API_KEY)

    def available(self) -> bool:
        return bool(self.base_url)

@dataclass(frozen=True)
class ScrapeResult:
    url: str
    title: str
    status_code: int
    markdown: str

def scrape_url(url: str, config: FirecrawlConfig, *, only_main_content: bool = True) -> ScrapeResult:
    """POST /v1/scrape → markdown. Raises on non-2xx or success=false."""
    payload = json.dumps({
        "url": url, "formats": ["markdown"], "onlyMainContent": only_main_content,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    req = urllib.request.Request(
        f"{config.base_url}/v1/scrape", data=payload, headers=headers, method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    if not body.get("success"):
        raise RuntimeError(f"firecrawl scrape failed: {body}")
    data = body["data"]; meta = data.get("metadata", {})
    return ScrapeResult(
        url=meta.get("sourceURL", url),
        title=meta.get("title", ""),
        status_code=int(meta.get("statusCode", 0)),
        markdown=data.get("markdown", ""),
    )
```

Config từ settings/env (thêm vào `src/config/settings.py` cạnh TAVILY/BRAVE):
```python
FIRECRAWL_BASE_URL = os.environ.get("FIRECRAWL_BASE_URL", "")   # "" ⇒ tắt
FIRECRAWL_API_KEY  = os.environ.get("FIRECRAWL_API_KEY", "")
```
`.env` local:
```
FIRECRAWL_BASE_URL=http://localhost:3002
FIRECRAWL_API_KEY=local-selfhost
```

**Dùng ở đâu:**
- Trong pack ToolProvider (`domain-packs/*/tools.py`): gọi `scrape_url()` trong `read(kind=...)` khi 1 report cần nội dung URL (vd researcher-pack đọc bài báo).
- Hoặc như agent-callable tool nếu MPM có cơ chế expose tool cho runtime tool-calling (v20 `read_only_toolset`).

### Cách B — Firecrawl làm reader trong researcher-pack (nếu làm nghề "researcher")

Đúng định hướng harness office: **researcher-pack** cần đọc web → Firecrawl là `ToolProvider.read()` của pack đó. Pack `tools.py`:
```python
class ResearchToolProvider:
    def read(self, kind, config, settings):
        if kind == "web-digest":
            urls = config.get("urls", [])
            fc = FirecrawlConfig(settings.firecrawl_base_url, settings.firecrawl_api_key)
            return [scrape_url(u, fc) for u in urls]
        ...
```
→ Lõi không biết Firecrawl; pack tự lo (đúng `git diff src/ = ∅` nếu đặt `firecrawl_tool.py` là shared util — hoặc để trong pack luôn cho sạch).

---

## 4. ⚠️ An toàn — BẮT BUỘC giữ (Firecrawl = năng lực rủi ro cao)

Nội dung web scrape về là **UNTRUSTED** (có thể chứa prompt-injection). Phải:

1. **KHÔNG cho agent tự ý scrape URL tùy ý mà không kiểm.** Nếu expose vào tool-calling runtime (v20), scrape-tool phải qua **policy shim + read-allowlist** như `read_only_toolset.py` — Firecrawl là READ (không mutation), nhưng nội dung trả về phải được coi như dữ liệu untrusted.
2. **external=zero-memory + audience-aware:** nội dung scrape KHÔNG được fold vào external-audience deliverable trừ khi đã sanitize. Coi markdown scrape như untrusted-content (giống `format_internal_content` quarantine của skill-loader).
3. **Target-URL safety:** chặn scrape các URL nội bộ/loopback/metadata (SSRF) — tự validate trước khi gọi Firecrawl. (Firecrawl hosted có chặn sẵn; self-host thì reader của MPM nên tự chặn `localhost`, `169.254.169.254`, private IP để agent không dùng Firecrawl làm bàn đạp SSRF.)
4. **Mọi WRITE vẫn qua Action Gateway.** Firecrawl chỉ READ; kết quả scrape đi vào graph như dữ liệu, mọi mutation phát sinh (tạo Confluence page từ nội dung scrape) vẫn qua gateway như thường.
5. **Không phụ thuộc cứng:** `FIRECRAWL_BASE_URL` rỗng ⇒ tính năng tắt (Docker chưa chạy). Fail mềm, báo rõ "Firecrawl local offline", không crash graph.

---

## 5. Kiểm thử

```bash
# 1. Firecrawl sống?
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3002/    # 200

# 2. scrape thật
curl -s -X POST http://localhost:3002/v1/scrape \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com","formats":["markdown"]}' | python3 -m json.tool

# 3. unit test firecrawl_tool: inject fake urlopen (như web_search_tool test),
#    KHÔNG gọi Firecrawl thật → test offline. Verify parse markdown/metadata + raise khi success=false.

# 4. xác nhận request THẬT tới container (bằng chứng đi qua Docker):
docker compose -f ~/workspace/firecrawl/docker-compose.yaml logs api --since 5m | grep "Scraping URL"
```

---

## 6. Vận hành
- **Firecrawl phụ thuộc Docker chạy.** Đã set auto-start (Docker Desktop open-at-login + compose `restart: unless-stopped`) nên reboot tự lên. Nếu tắt Docker thủ công → `docker compose up -d` lại.
- Endpoint chỉ nghe **loopback** — không expose ra ngoài máy. An toàn cho local-only single-operator.
- Nếu deploy MPM lên máy khác không có Firecrawl → để `FIRECRAWL_BASE_URL` rỗng, hoặc trỏ Firecrawl hosted (`https://api.firecrawl.dev` + key thật).

---

## 7. Câu hỏi chưa giải quyết
1. **Firecrawl thuộc shared-util (`src/tools/`) hay pack-local?** Nếu nhiều pack dùng → shared; nếu chỉ researcher-pack → để trong pack cho `git diff src/ = ∅`. Cần chốt theo số pack sẽ dùng.
2. **Expose vào tool-calling runtime (v20) hay chỉ reader-in-graph?** Nếu vào runtime tool-calling thì phải thêm vào `read_only_toolset` với policy-shim + SSRF-guard (mục §4.1/4.3). Reader-in-graph đơn giản hơn, ít bề mặt tấn công.
3. **SSRF-guard đặt ở đâu** — trong `firecrawl_tool.scrape_url` (chặn tại nguồn, an toàn nhất) hay ở caller? Đề xuất: chặn tại nguồn.
4. **Crawl nhiều trang** (`/v1/crawl` async job) có cần không, hay chỉ scrape 1 URL đủ cho use-case PM/researcher? Crawl async phức tạp hơn (poll job) — YAGNI trừ khi cần crawl cả site.
