// The composer's @-mention matching (pure helper — the full composer needs a live API,
// covered by the Playwright E2E instead).
import { expect, test } from 'vitest'
import { filterStaffForMention } from './assign-composer'

const STAFF = [
  { id: 'noi-dung', domain: 'office' },
  { id: 'nghien-cuu', domain: 'office' },
  { id: 'kiem-dinh', domain: 'office' },
]

test('bare @ lists @all plus the whole roster', () => {
  const out = filterStaffForMention('@', STAFF)
  expect(out.map((s) => s.id)).toEqual(['all', 'noi-dung', 'nghien-cuu', 'kiem-dinh'])
})

test('partial narrows by prefix first, then substring', () => {
  // prefix matches lead; substring matches (kiem-diNh) follow — both reachable by typing.
  expect(filterStaffForMention('@n', STAFF).map((s) => s.id)).toEqual([
    'noi-dung', 'nghien-cuu', 'kiem-dinh',
  ])
  expect(filterStaffForMention('@dinh', STAFF).map((s) => s.id)).toEqual(['kiem-dinh'])
})

test('no dropdown without a leading @ or once the mention token is complete', () => {
  expect(filterStaffForMention('viết bài', STAFF)).toEqual([])
  expect(filterStaffForMention('@noi-dung viết bài', STAFF)).toEqual([])
})

// v56: the assign-time web-search warning — fires ONLY on an explicit ready=false for a
// PIC that opted in ('@all' = any opted-in staff); undefined (payload not landed) stays quiet.
import { webSearchHintNeeded } from './assign-composer'

const WEB_STAFF = [
  { id: 'noi-dung', domain: 'office', web_search: false },
  { id: 'nghien-cuu', domain: 'office', web_search: true },
]

test('hint fires only for an opted-in PIC when ready is explicitly false', () => {
  expect(webSearchHintNeeded('nghien-cuu', WEB_STAFF, false)).toBe(true)
  expect(webSearchHintNeeded('noi-dung', WEB_STAFF, false)).toBe(false)
  expect(webSearchHintNeeded('nghien-cuu', WEB_STAFF, true)).toBe(false)
  expect(webSearchHintNeeded('nghien-cuu', WEB_STAFF, undefined)).toBe(false)
  expect(webSearchHintNeeded('', WEB_STAFF, false)).toBe(false)
})

test('@all hints when ANY staff opted in, stays quiet when none did', () => {
  expect(webSearchHintNeeded('all', WEB_STAFF, false)).toBe(true)
  expect(webSearchHintNeeded('all', [{ id: 'noi-dung', domain: 'office' }], false)).toBe(false)
})
