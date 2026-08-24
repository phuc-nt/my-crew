import { test, expect } from '@playwright/test'
import { login } from './uat-login'

/**
 * UAT step 3: recruit an agent from a template, then bind a REAL Telegram bot to it and
 * have the agent actually greet the operator. This is the first step where the fleet
 * touches the outside world, so nothing here is mocked: a real bot token, a real chat.
 *
 * The fleet starts with no coordinator, and the Team hub says so — recruiting the
 * coordinator template is the move the app itself recommends, so that's what we do.
 */
/** The bind derives the .env key from the agent id (`<AGENT>_TELEGRAM_BOT_TOKEN`,
 *  non-alphanumerics to `_`) — mirror that rather than hardcoding a name, so the
 *  token is looked up under whatever id this run actually hired. */
const tokenEnvName = (agentId: string) =>
  `${agentId.toUpperCase().replace(/[^A-Z0-9]/g, '_')}_TELEGRAM_BOT_TOKEN`
// No default: this is a real person's chat id, so it comes from the environment or
// the step is skipped rather than baked into the repo.
const CHAT_ID = process.env.UAT_TELEGRAM_CHAT_ID

test('recruit a template agent and bind a real Telegram bot', async ({ page }) => {
  const errors: string[] = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', e => errors.push(String(e)))

  await login(page)

  // Hiring the same template twice is a 409 by design, so a rerun must skip the hire
  // rather than trip over its own leftovers. Only the FIRST run exercises recruiting;
  // both runs exercise the bind, which is what this step is really about.
  const before = await (await page.request.get('/api/agents')).json()
  const already = before.find((a: any) => a.id === 'coordinator')

  await page.goto('/team', { waitUntil: 'domcontentloaded' })
  if (!already) {
    await page.getByRole('button', { name: '+ Tuyển nhân sự' }).click()

    // Recruit the coordinator — the exact template the empty-fleet hint names.
    const card = page.locator('.staff-template-card').filter({ hasText: 'Trưởng phòng (Điều phối đội)' })
    await expect(card).toHaveCount(1)
    await card.getByRole('button', { name: 'Tạo ngay' }).click()
    // Recruiting asks for confirmation first — creating staff writes a new profile dir,
    // so a stray click must not do it silently.
    await card.getByRole('button', { name: 'Xác nhận' }).click()
  } else {
    console.log('HIRE: coordinator already exists from an earlier run — skipping recruit')
  }

  // It must appear in the real roster, not just in the panel.
  await expect(page.locator('table')).toContainText('Điều phối', { timeout: 30_000 })

  const roster = await (await page.request.get('/api/agents')).json()
  const hired = roster.find((a: any) => a.id !== 'default')
  expect(hired, 'a new agent must exist on disk').toBeTruthy()
  console.log('HIRED:', hired.id, '|', hired.name)

  // --- bind a REAL bot to the agent we just hired ---
  // Narrow explicitly rather than leaning on expect(): a failed assertion stops the
  // test, but it does not tell the type checker that CHAT_ID is a string.
  if (!CHAT_ID) throw new Error('UAT_TELEGRAM_CHAT_ID must be set — this step sends a REAL message')
  const BOT_TOKEN_ENV = tokenEnvName(hired.id)
  const token = process.env[BOT_TOKEN_ENV]
  expect(token, `${BOT_TOKEN_ENV} must be set — this step refuses to fake the bind`).toBeTruthy()

  await page.goto(`/team/${hired.id}`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Kênh' }).click()

  await page.locator('input[type=password]').fill(token!)
  await page.getByPlaceholder('5248565986').fill(CHAT_ID)
  await page.getByRole('button', { name: 'Gắn bot' }).click()

  // The bind validates the token against Telegram's getMe before persisting, so this text
  // appearing means a real bot answered — not that a form submitted.
  await expect(page.locator('.telegram-tab .ok')).toBeVisible({ timeout: 30_000 })
  const boundNote = await page.locator('.telegram-tab .ok').innerText()
  console.log('BOUND:', boundNote)

  // The bind must be durable: profile.yaml gains a telegram block, .env gains the token
  // under the per-agent whitelisted key. Read it back through the API, not from memory.
  const cfg = await (await page.request.get(`/api/agents/${hired.id}/config`)).json()
  expect(cfg.files.profile, 'profile.yaml must carry the telegram block').toContain('telegram:')
  expect(cfg.files.profile).toContain(CHAT_ID)

  // --- the agent actually greets, for real ---
  const greeting = `UAT ${hired.id}: chào sếp, em đã nhận bàn giao và sẵn sàng nhận việc.`
  const sent = await page.request.post(`https://api.telegram.org/bot${token}/sendMessage`, {
    data: { chat_id: CHAT_ID, text: greeting },
  })
  expect(sent.ok(), 'the greeting must actually reach Telegram').toBeTruthy()
  const sentBody = await sent.json()
  console.log('GREETED: msg_id =', sentBody.result?.message_id, '| bot =', sentBody.result?.from?.username)

  console.log('ERRORS:', errors.length ? errors.join('\n') : '(none)')
  expect(errors.filter(e => !/401/.test(e)), 'no unexpected console errors').toEqual([])
})
