import { defineConfig, devices } from '@playwright/test'

// Live verification: real backend on 127.0.0.1:8765, real data, no page.route mocks.
// Deliberately separate from playwright.config.ts, whose whole premise is a mocked API
// against `vite dev`. Not part of CI — it needs a running fleet.
export default defineConfig({
  testDir: './e2e-live',
  timeout: 60_000,
  retries: 0,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8765', trace: 'off' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
})
