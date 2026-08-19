#!/usr/bin/env bash
# Cold start từ wheel thật — người mới cài đặt lần đầu đi đúng đường này.
#
# Vì sao có script: gate 0.12.0 chạy toàn bộ phần này bằng tay, và cái nó bắt được (bundle
# FE thiếu, tài nguyên _shipped rơi khỏi wheel, home trống không seed nổi) đều là lỗi CHỈ
# lộ ra trên máy sạch — suite pytest chạy trong repo không bao giờ thấy. Chạy tay thì lần
# sau lại phải nhớ mà chạy.
#
# Script tự dựng và tự dọn: wheel mới, venv sạch, MY_CREW_HOME mới tinh, không đụng vào
# .env hay dữ liệu thật của người dùng. Không mạng, không secret.
#
#   scripts/cold-start-smoke.sh            # chỉ phần backend
#   scripts/cold-start-smoke.sh --browser  # thêm màn đăng nhập thật qua Playwright
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/cold-start-XXXXXX")"
PORT="${COLD_START_PORT:-8799}"
WITH_BROWSER=0
[[ "${1:-}" == "--browser" ]] && WITH_BROWSER=1

SERVER_PID=""
cleanup() {
  [[ -n "$SERVER_PID" ]] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

say() { printf '\n=== %s\n' "$1"; }
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

say "1/6 dựng wheel"
cd "$REPO_ROOT"
uv build --out-dir "$WORK/dist" >/dev/null 2>&1 || fail "uv build hỏng"
WHEEL="$(ls "$WORK"/dist/*.whl | head -1)"
[[ -n "$WHEEL" ]] || fail "không thấy wheel"
printf 'wheel: %s\n' "$(basename "$WHEEL")"

# Tài nguyên _shipped nằm ngoài package nên đi qua force-include; nó rơi khỏi wheel là
# cài xong CLI chạy nhưng không seed nổi profile nào — im lặng cho tới lúc người dùng thử.
SHIPPED_COUNT="$(unzip -l "$WHEEL" | grep -c '_shipped/' || true)"
[[ "$SHIPPED_COUNT" -ge 60 ]] || fail "_shipped chỉ có $SHIPPED_COUNT file (chờ ≥60)"
# Bundle FE được commit vào repo, KHÔNG dựng lúc cài — thiếu là cài xong mở ra trắng trang.
ASSET_COUNT="$(unzip -l "$WHEEL" | grep -c 'server/static/app/' || true)"
[[ "$ASSET_COUNT" -ge 5 ]] || fail "bundle FE chỉ có $ASSET_COUNT file (chờ ≥5)"
printf '_shipped: %s file · FE dist: %s file\n' "$SHIPPED_COUNT" "$ASSET_COUNT"

say "2/6 cài vào venv sạch"
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --disable-pip-version-check "$WHEEL" || fail "cài wheel hỏng"
BIN="$WORK/venv/bin/my-crew"
[[ -x "$BIN" ]] || fail "không có lệnh my-crew sau khi cài"

export MY_CREW_HOME="$WORK/home"
# Home mới tinh, KHÔNG chép .env — cold start thật là không có khoá nào cả.
mkdir -p "$MY_CREW_HOME"
# Cổng riêng: 8765 là chỗ dịch vụ thật của người dùng đang chạy, smoke không được giẫm lên.
export PORT="$PORT"

say "3/6 my-crew --version"
"$BIN" --version || fail "--version hỏng"

say "4/6 home trống tự seed"
# Đây là bước cold start hay gãy nhất: home trống phải tự tạo profile mẫu + registry,
# chứ không phải nổ vì thiếu file.
"$BIN" agent list >"$WORK/agent-list.txt" 2>&1 || {
  cat "$WORK/agent-list.txt" >&2
  fail "agent list trên home trống bị lỗi"
}
[[ -f "$MY_CREW_HOME/registry.yaml" ]] || fail "registry.yaml không được tạo"
printf 'registry + profile đã seed\n'

# Cổng bận thì server chết ngay và log chỉ nói "server chết" — nói thẳng lý do ra đây
# rẻ hơn nhiều so với đi mò lúc CI đỏ.
if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "cổng $PORT đang bận — đặt COLD_START_PORT sang cổng khác"
fi

say "5/6 serve --web-only"
"$BIN" serve --web-only >"$WORK/serve.log" 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 40); do
  curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && break
  kill -0 "$SERVER_PID" 2>/dev/null || { cat "$WORK/serve.log" >&2; fail "server chết khi khởi động"; }
  sleep 0.5
done
curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null || {
  cat "$WORK/serve.log" >&2
  fail "/health không lên sau 20 giây"
}
printf '/health: 200\n'

# Trang SPA phải phục vụ được: 200 + có thẻ script trỏ vào bundle đã cài.
INDEX="$(curl -fsS "http://127.0.0.1:$PORT/" || true)"
grep -q '<script' <<<"$INDEX" || fail "trang chủ không có bundle FE"
printf 'trang chủ: có bundle\n'

say "6/6 màn đăng nhập"
if [[ "$WITH_BROWSER" -eq 1 ]]; then
  cd "$REPO_ROOT/web"
  COLD_START_URL="http://127.0.0.1:$PORT" \
    npx playwright test --config=playwright.cold-start.config.ts || fail "smoke browser đỏ"
else
  printf 'bỏ qua (chạy với --browser để mở trình duyệt thật)\n'
fi

printf '\nCOLD START OK\n'
