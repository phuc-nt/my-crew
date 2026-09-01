// What a staff template brings with it, as chips — the answer to "what do I actually get
// if I press Tạo ngay?", which the API has always returned and the card used to hide.
import type { UiKey } from '../../../i18n/dictionary'
import type { StaffTemplate } from '../../../types'

const RUNTIME_LABEL_KEY: Record<string, UiKey> = {
  native: 'staffTemplatePicker.runtimeNative',
  create_agent: 'staffTemplatePicker.runtimeCreateAgent',
  deep_agent: 'staffTemplatePicker.runtimeDeepAgent',
}

type Translate = (key: UiKey, params?: Record<string, string | number>) => string

export function templateChips(template: StaffTemplate, t: Translate): string[] {
  const chips: string[] = []
  if (template.web_search) chips.push(t('staffTemplatePicker.chipWebSearch'))
  if (template.has_skills) chips.push(t('staffTemplatePicker.chipSkills'))
  if (template.reports.length > 0)
    chips.push(t('staffTemplatePicker.chipReports', { kinds: template.reports.join(', ') }))
  // A template can arrive pre-scheduled, which means the agent starts running on its own
  // the moment it exists. That is the single most surprising thing a one-click create can
  // do, so it gets a chip rather than living only in the profile the CEO never opens.
  const scheduled = Object.keys(template.schedule)
  if (scheduled.length > 0)
    chips.push(t('staffTemplatePicker.chipSchedule', { kinds: scheduled.join(', ') }))
  const runtimeKey = RUNTIME_LABEL_KEY[template.recommended_runtime]
  chips.push(runtimeKey ? t(runtimeKey) : template.recommended_runtime)
  return chips
}
