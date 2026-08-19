import { chromium } from '@playwright/test'
const SHOT = '/private/tmp/claude-501/-Users-phucnt-workspace-my-crew/56284c3a-3a6a-4129-a128-f451a8d2c7fa/scratchpad'
const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1440, height: 900 } })
const errs = []
p.on('console', m => { if (m.type() === 'error') errs.push(m.text()) })
p.on('response', r => { if (r.url().includes('/api/') && r.status() >= 400) errs.push(`${r.status()} ${r.url()}`) })
await p.goto('http://localhost:8799/chat', { waitUntil: 'networkidle' })
if (await p.locator('input[type=password]').count()) {
  const ins = p.locator('input')
  await ins.nth(0).fill('ceo'); await ins.nth(1).fill('coldstart123')
  await p.locator('button[type=submit], button:has-text("Đăng nhập")').first().click()
  await p.waitForTimeout(2000)
}
await p.goto('http://localhost:8799/chat', { waitUntil: 'networkidle' })
await p.waitForTimeout(2500)
await p.screenshot({ path: `${SHOT}/cs2-chat-state.png`, fullPage: true })
console.log('URL:', p.url())
console.log('TEXT >>>', (await p.locator('body').innerText()).replace(/\s+/g,' ').slice(0, 900))
console.log('inputs:', await p.locator('.office-composer input, .ops-composer input').count())
console.log('errors=', errs.length, errs.slice(0,4))
await b.close()
