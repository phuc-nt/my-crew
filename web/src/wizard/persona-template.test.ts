import { expect, test } from 'vitest'
import { generateSoulMarkdown } from './persona-template'

test('generateSoulMarkdown builds SOUL.md from role + goals', () => {
  const md = generateSoulMarkdown('PM for Acme', 'Ship weekly reports\nTrack budget')
  expect(md).toContain('You are an agent acting as: PM for Acme.')
  expect(md).toContain('- Ship weekly reports')
  expect(md).toContain('- Track budget')
})

test('generateSoulMarkdown handles empty inputs', () => {
  const md = generateSoulMarkdown('', '')
  expect(md).toContain('(role not set)')
  expect(md).toContain('(no goals set)')
})
