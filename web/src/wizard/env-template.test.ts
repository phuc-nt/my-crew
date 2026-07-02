import { expect, test } from 'vitest'
import { buildEnvTemplate } from './env-template'

test('buildEnvTemplate lists the ATLASSIAN vars once for jira+confluence', () => {
  const tpl = buildEnvTemplate(['jira', 'confluence', 'slack'])
  expect(tpl).toContain('ATLASSIAN_SITE_NAME=')
  expect(tpl).toContain('ATLASSIAN_API_TOKEN=')
  expect(tpl.match(/ATLASSIAN_API_TOKEN=/g)).toHaveLength(1)
  expect(tpl).toContain('SLACK_XOXC_TOKEN=')
})

test('buildEnvTemplate never includes secret values, only names', () => {
  const tpl = buildEnvTemplate(['slack'])
  expect(tpl).not.toMatch(/SLACK_XOXC_TOKEN=.+/)
})

test('buildEnvTemplate handles empty server list', () => {
  const tpl = buildEnvTemplate([])
  expect(tpl).toContain('no extra tokens needed')
})
