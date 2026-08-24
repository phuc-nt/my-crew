import { defineConfig, devices } from '@playwright/test'

// Cold-start UAT: a CLEAN MY_CREW_HOME served on 8799 by a pip-installed my-crew.
// Separate from playwright.live.config.ts (which points at the real fleet on 8765) —
// this one's whole premise is a machine that has never been configured.
export default defineConfig({
  testDir: './e2e-uat',
  timeout: 420_000,
  retries: 0,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: 'http://127.0.0.1:8799', trace: 'off', video: 'off' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
})
