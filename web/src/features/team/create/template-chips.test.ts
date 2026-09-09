// templateChips: the one place that decides what a template card promises. The pack
// skill chip is new (v97) and must carry the NAMES, sit before reports/schedule, and stay
// absent when a template brings no pack skills.
import { expect, test } from 'vitest'
import type { StaffTemplate } from '../../../types'
import { templateChips } from './template-chips'

const t = (key: string, params?: Record<string, string | number>) =>
  params ? `${key}(${Object.values(params).join('|')})` : key

const base: StaffTemplate = {
  role_id: 'qa',
  role: 'Kiểm định',
  domain: 'office',
  reports: [],
  bindings_hint: [],
  persona: '',
  web_search: false,
  recommended_runtime: 'native',
  schedule: {},
  has_skills: false,
  skills: [],
}

test('a bare native template yields only the runtime chip', () => {
  expect(templateChips(base, t)).toEqual(['staffTemplatePicker.runtimeNative'])
})

test('pack skills are listed by name, between the skills flag and the reports', () => {
  const pm: StaffTemplate = {
    ...base,
    role_id: 'pm-coordinator',
    domain: 'pm',
    reports: ['daily', 'weekly'],
    schedule: { daily: '0 8 * * *' },
    has_skills: false,
    skills: ['flag-risk', 'prioritize-blockers'],
  }
  expect(templateChips(pm, t)).toEqual([
    'staffTemplatePicker.chipPackSkills(flag-risk, prioritize-blockers)',
    'staffTemplatePicker.chipReports(daily, weekly)',
    'staffTemplatePicker.chipSchedule(daily)',
    'staffTemplatePicker.runtimeNative',
  ])
})

test('web search and template-dir skills keep their own chips ahead of the pack list', () => {
  const researcher: StaffTemplate = {
    ...base,
    role_id: 'researcher',
    web_search: true,
    has_skills: true,
    recommended_runtime: 'deep_agent',
    skills: ['read-meta-ads-insights'],
  }
  expect(templateChips(researcher, t)).toEqual([
    'staffTemplatePicker.chipWebSearch',
    'staffTemplatePicker.chipSkills',
    'staffTemplatePicker.chipPackSkills(read-meta-ads-insights)',
    'staffTemplatePicker.runtimeDeepAgent',
  ])
})

test('an unknown runtime falls through as its raw id', () => {
  expect(templateChips({ ...base, recommended_runtime: 'custom_rt' }, t)).toEqual(['custom_rt'])
})
