#!/usr/bin/env bash
# demo-mode.sh — bật/tắt "chế độ demo": công ty mẫu + đội nhân sự chuẩn + văn phòng
# đang hoạt động, sẵn sàng cho khách xem. KHÔNG phá data thật: mọi thứ bị thay đều
# được MV (không copy-đè) vào .demo-backup/ và trả lại nguyên vẹn khi tắt.
#
#   scripts/demo-mode.sh on      # backup data thật -> swap fixtures demo -> seed -> restart app
#   scripts/demo-mode.sh off     # xoá dấu vết demo -> trả data thật -> restart app
#   scripts/demo-mode.sh status  # đang ở chế độ nào
#
# Phạm vi swap: registry.yaml, company.yaml, profiles/<nhân sự demo>/,
# .data/office_room.sqlite3, .data/team_tasks.sqlite3 (timeline/việc sạch cho demo).
# KHÔNG đụng: .env, approvals/budget/audit của agent thật, mọi thứ khác trong .data.
#
# Lưu ý: registry.yaml là user data (gitignored từ v18) — demo swap không làm repo dirty.
# Lưu ý 2: task giao THẬT trong lúc demo (id uuid) nằm trong store demo bị bỏ khi off;
# thư mục artifact hex của chúng còn lại trên đĩa nhưng không API nào với tới (rác vô
# hại, xoá tay nếu muốn: .data/artifacts/team-tasks/<12-hex>).

set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP=.demo-backup
MARKER=$BACKUP/DEMO_ON
SERVICE_PID_FILE=$BACKUP/service.pid
PORT="${PORT:-8765}"
DEMO_AGENTS=(truong-phong nghien-cuu noi-dung phan-tich kiem-dinh thiet-ke)
SWAP_STORES=(office_room.sqlite3 team_tasks.sqlite3 captures.sqlite3)

restart_app() {
  lsof -ti ":$PORT" 2>/dev/null | xargs kill 2>/dev/null || true
  sleep 1
  mkdir -p "$BACKUP"
  nohup uv run python -c "from my_crew.server.app import main; main()" \
    > "$BACKUP/app-$PORT.log" 2>&1 &
  # chờ app lên (tối đa ~10s)
  for _ in $(seq 1 20); do
    sleep 0.5
    if curl -s -o /dev/null "http://127.0.0.1:$PORT/health"; then
      echo "→ App: http://127.0.0.1:$PORT"
      return 0
    fi
  done
  echo "CẢNH BÁO: app chưa phản hồi — xem log $BACKUP/app-$PORT.log" >&2
}

demo_on() {
  if [ -f "$MARKER" ]; then
    echo "Demo mode ĐANG BẬT rồi (tắt bằng: scripts/demo-mode.sh off)"; exit 1
  fi
  mkdir -p "$BACKUP/profiles" "$BACKUP/data"

  # 1) backup config thật (mv — bản gốc rời khỏi chỗ, không thể bị đè nhầm)
  mv registry.yaml "$BACKUP/registry.yaml"
  if [ -f company.yaml ]; then mv company.yaml "$BACKUP/company.yaml"; fi
  for id in "${DEMO_AGENTS[@]}"; do
    if [ -d "profiles/$id" ]; then mv "profiles/$id" "$BACKUP/profiles/$id"; fi
  done
  for db in "${SWAP_STORES[@]}"; do
    if [ -f ".data/$db" ]; then mv ".data/$db" "$BACKUP/data/$db"; fi
    # WAL/SHM đi kèm DB (nếu có) — phải đi cùng nhau, không được để lẫn
    for ext in -wal -shm; do
      if [ -f ".data/$db$ext" ]; then mv ".data/$db$ext" "$BACKUP/data/$db$ext"; fi
    done
  done

  # 2) swap fixtures demo vào (copy — fixtures gốc trong demo/ giữ nguyên)
  cp demo/registry.yaml registry.yaml
  cp demo/company.yaml company.yaml
  for id in "${DEMO_AGENTS[@]}"; do
    cp -R "demo/profiles/$id" "profiles/$id"
  done

  # 3) seed timeline văn phòng demo (đi qua đúng writer production)
  uv run python demo/seed_office_events.py

  date > "$MARKER"
  restart_app
  start_demo_service
  echo "✅ DEMO MODE: BẬT — công ty demo + đội 6 nhân sự + văn phòng đang hoạt động."
  echo "   Mở Văn phòng → Văn phòng 3D để xem cảnh sống. Tắt: scripts/demo-mode.sh off"
}

demo_off() {
  if [ ! -f "$MARKER" ]; then
    echo "Demo mode đang TẮT (bật bằng: scripts/demo-mode.sh on)"; exit 1
  fi

  # 1) gỡ mọi thứ demo đã đặt vào
  rm -f registry.yaml company.yaml
  for id in "${DEMO_AGENTS[@]}"; do
    rm -rf "profiles/$id"
  done
  for db in "${SWAP_STORES[@]}"; do
    rm -f ".data/$db" ".data/$db-wal" ".data/$db-shm"
  done
  # v17: dọn artifact task demo (id prefix demo- do seed đặt) — không để rác trong
  # artifacts thật; chỉ xoá demo-* (không đoán uuid của task giao thật trong demo).
  rm -rf .data/artifacts/team-tasks/demo-* 2>/dev/null || true

  # 2) trả data thật về đúng chỗ
  mv "$BACKUP/registry.yaml" registry.yaml
  if [ -f "$BACKUP/company.yaml" ]; then mv "$BACKUP/company.yaml" company.yaml; fi
  for id in "${DEMO_AGENTS[@]}"; do
    if [ -d "$BACKUP/profiles/$id" ]; then mv "$BACKUP/profiles/$id" "profiles/$id"; fi
  done
  for db in "${SWAP_STORES[@]}"; do
    if [ -f "$BACKUP/data/$db" ]; then mv "$BACKUP/data/$db" ".data/$db"; fi
    for ext in -wal -shm; do
      if [ -f "$BACKUP/data/$db$ext" ]; then mv "$BACKUP/data/$db$ext" ".data/$db$ext"; fi
    done
  done

  stop_demo_service
  rm -f .data/coordinator.heartbeat
  rm -f "$MARKER"
  rmdir "$BACKUP/profiles" "$BACKUP/data" 2>/dev/null || true
  restart_app
  echo "✅ DEMO MODE: TẮT — data thật đã trả lại nguyên vẹn."
}

# v16: demo chạy KÈM bộ điều phối thật (my_crew.runtime.service) — không thì việc giao trong
# demo kẹt ở "đã nhận việc" y như bug thật. PID FILE: off giết đúng process của demo,
# không bao giờ pkill theo tên (tránh giết service thật của user).
start_demo_service() {
  if pgrep -f "my_crew.runtime.service" >/dev/null 2>&1; then
    echo "LỖI: đang có bộ điều phối khác chạy (my_crew.runtime.service) — tắt nó trước khi bật demo" >&2
    echo "     (2 ticker cùng lúc sẽ tranh nhau store)." >&2
    echo "     Đang hoàn tác demo swap (demo off)..." >&2
    demo_off
    exit 1
  fi
  # macOS không có setsid; nohup + PID trực tiếp là đủ (worker con là process ngắn hạn
  # tự thoát — kill service PID không để mồ côi gì lâu dài).
  nohup .venv/bin/python -m my_crew.runtime.service > "$BACKUP/service.log" 2>&1 &
  echo $! > "$SERVICE_PID_FILE"
  sleep 1
  if kill -0 "$(cat "$SERVICE_PID_FILE" 2>/dev/null)" 2>/dev/null; then
    echo "→ Bộ điều phối demo: PID $(cat "$SERVICE_PID_FILE")"
  else
    echo "CẢNH BÁO: bộ điều phối demo chưa lên — xem $BACKUP/service.log" >&2
  fi
}

stop_demo_service() {
  if [ -f "$SERVICE_PID_FILE" ]; then
    pid=$(cat "$SERVICE_PID_FILE")
    kill "$pid" 2>/dev/null || true
    rm -f "$SERVICE_PID_FILE"
  fi
}

demo_status() {
  if [ -f "$MARKER" ]; then
    echo "DEMO MODE: BẬT (từ $(cat "$MARKER"))"
    if [ -f "$SERVICE_PID_FILE" ] && kill -0 "$(cat "$SERVICE_PID_FILE")" 2>/dev/null; then
      echo "Bộ điều phối demo: ĐANG CHẠY (PID $(cat "$SERVICE_PID_FILE"))"
    else
      echo "Bộ điều phối demo: KHÔNG chạy"
    fi
    if [ -f .data/coordinator.heartbeat ]; then
      echo "Heartbeat: $(date -r .data/coordinator.heartbeat)"
    fi
  else
    echo "DEMO MODE: TẮT"
  fi
}

case "${1:-}" in
  on) demo_on ;;
  off) demo_off ;;
  status) demo_status ;;
  *) echo "Cách dùng: scripts/demo-mode.sh {on|off|status}"; exit 1 ;;
esac
