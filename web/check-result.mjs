import { chromium } from '@playwright/test'
const SHOT = '/private/tmp/claude-501/-Users-phucnt-workspace-my-crew/56284c3a-3a6a-4129-a128-f451a8d2c7fa/scratchpad'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
await p.goto('http://localhost:8799/chat', { waitUntil: 'networkidle' })
if (await p.locator('input[type=password]').count()) {
  const ins = p.locator('input')
  await ins.nth(0).fill('ceo'); await ins.nth(1).fill('coldstart123')
  await p.locator('button[type=submit], button:has-text("Đăng nhập")').first().click()
  await p.waitForTimeout(2000)
}
for (const [name, url] of [['chat','/chat'], ['work','/work'], ['office','/office']]) {
  await p.goto(`http://localhost:8799${url}`, { waitUntil: 'networkidle' })
  await p.waitForTimeout(2500)
  await p.screenshot({ path: `${SHOT}/cs2-final-${name}.png`, fullPage: true })
  console.log(`--- ${name} ---`, (await p.locator('body').innerText()).replace(/\s+/g,' ').slice(0, 800))
}
await b.close()
