import { defineConfig, devices } from '@playwright/test'

// Cấu hình riêng cho smoke cold-start (`scripts/cold-start-smoke.sh --browser`).
//
// Khác hẳn `playwright.config.ts`: bộ kia mock mọi lời gọi /api trong browser và tự dựng
// `vite dev`. Ở đây thì ngược lại mới có ý nghĩa — backend THẬT chạy từ wheel vừa cài, và
// thứ cần chứng minh chính là bundle đã cài phục vụ được màn đăng nhập. Mock ở đây sẽ
// làm bài test mất sạch giá trị.
//
// Không có `webServer`: script bash dựng server rồi truyền địa chỉ vào qua COLD_START_URL.
export default defineConfig({
  testDir: './e2e-cold-start',
  timeout: 30_000,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.COLD_START_URL || 'http://127.0.0.1:8799',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
})
