import { defineConfig, devices } from '@playwright/test'

// v56: smoke tests for the v55 cockpit layout. jsdom cannot measure layout ("suite
// xanh ≠ chạy được" happened two rounds in a row), so these run in real chromium
// against `vite dev` with every /api call mocked inside the browser via page.route —
// secret-free, no Python backend, the vite proxy is never reached.
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // Flaky = bug here: layout assertions are deterministic DOM measurements, so a retry
  // that turns red into green would only hide a real race (plan phase-02 criteria).
  retries: 0,
  reporter: process.env.CI ? [['github'], ['list']] : [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
