// v9 P1: label maps + formatters. The critical invariant is that a missing/undefined key
// NEVER renders blank (a run event can carry an undefined kind/status).
// v53: labelFor() takes an optional `t` (language-aware translate fn); with no `t` it
// falls back to DICT.vi. Assertions read DICT.vi directly (not hardcoded literals) so a
// dictionary wording change can't silently desync from what the test expects.
import { expect, test } from 'vitest'
import { DICT } from './i18n/dictionary'
import {
  KIND_LABEL,
  RUN_STATUS_LABEL,
  formatCron,
  formatDateTime,
  labelFor,
} from './labels'

test('labelFor maps a known key (DICT.vi fallback, no t passed)', () => {
  expect(labelFor(KIND_LABEL, 'daily')).toBe(DICT.vi['labels.kind.daily'])
  expect(labelFor(RUN_STATUS_LABEL, 'delivered')).toBe(DICT.vi['labels.runStatus.delivered'])
})

test('labelFor maps a known key via an explicit t (English)', () => {
  const t = (key: keyof typeof DICT.en) => DICT.en[key]
  expect(labelFor(KIND_LABEL, 'daily', t)).toBe(DICT.en['labels.kind.daily'])
  expect(labelFor(RUN_STATUS_LABEL, 'delivered', t)).toBe(DICT.en['labels.runStatus.delivered'])
})

test('labelFor returns the missing-marker for undefined/null/empty, never blank', () => {
  expect(labelFor(KIND_LABEL, undefined)).toBe(DICT.vi['labels.missing'])
  expect(labelFor(KIND_LABEL, null)).toBe(DICT.vi['labels.missing'])
  expect(labelFor(KIND_LABEL, '')).toBe(DICT.vi['labels.missing'])
})

test('labelFor shows an unknown-but-present key raw rather than hiding it', () => {
  expect(labelFor(KIND_LABEL, 'headcount')).toBe('headcount')
})

test('formatDateTime returns "" for empty/invalid input', () => {
  expect(formatDateTime('')).toBe('')
  expect(formatDateTime(null)).toBe('')
  expect(formatDateTime('not-a-date')).toBe('')
})

test('formatDateTime formats a valid ISO string (contains the date parts)', () => {
  const out = formatDateTime('2026-07-07T09:05:00+00:00')
  expect(out).toMatch(/07/) // day
  expect(out).toMatch(/:/) // HH:mm separator
})

test('formatCron: empty → "chạy thủ công"', () => {
  expect(formatCron(null)).toBe('chạy thủ công')
  expect(formatCron('')).toBe('chạy thủ công')
  expect(formatCron('   ')).toBe('chạy thủ công')
})

test('formatCron: daily wildcard', () => {
  expect(formatCron('0 9 * * *')).toBe('09:00 mỗi ngày')
})

test('formatCron: specific days → Vietnamese day names', () => {
  expect(formatCron('0 9 * * 1,3,5')).toBe('09:00 Thứ 2, Thứ 4, Thứ 6')
  expect(formatCron('30 14 * * 0')).toBe('14:30 Chủ nhật')
})

test('formatCron: unparseable → raw string', () => {
  expect(formatCron('bogus')).toBe('bogus')
})
