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
      testIgnore: /mobile-.*\.spec\.ts/,
    },
    // A separate project rather than a wider shared viewport: the desktop specs assert
    // the inline header row and the three-column chat hub, which the phone layout
    // deliberately replaces. Same mocked API, one viewport apart.
    // Phone metrics on chromium: `devices['iPhone 14 Pro']` would pull in webkit, which
    // this suite does not install (the repo only ships the chromium browser).
    {
      name: 'mobile',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 3,
        isMobile: true,
        hasTouch: true,
      },
      testMatch: /mobile-.*\.spec\.ts/,
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
