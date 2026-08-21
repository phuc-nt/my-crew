// v88 P4: the schedule row on the Profile tab. `schedule` is a `{kind: cron_expr}`
// mapping (types.ts:217, same shape the create-time form already uses) — edited here as
// one line per kind ("weekly_report = 0 9 * * 1"), which an operator reads far more
// easily than raw YAML. The PATCH replaces the WHOLE map (profile_patch's schedule
// block is a whole-block replace, not a leaf-merge), so this textarea is the single
// source of truth for every kind while editing, not just the one being touched.
import { useState } from 'react'
import { usePatchAgentProfileSettings } from '../../../api/queries/use-agent-detail-queries'
import { useLanguage } from '../../../i18n/language-context'
import { InlineEditRow } from './inline-edit-row'

interface Props {
  id: string
  schedule: Record<string, string>
  editingField: string | null
  setEditingField: (field: string | null) => void
}

function scheduleToText(schedule: Record<string, string>): string {
  return Object.entries(schedule)
    .map(([kind, cron]) => `${kind} = ${cron}`)
    .join('\n')
}

/** Parses "kind = cron" lines into a map. Throws with a line-specific message on the
 *  first malformed line — the caller surfaces it as the field error, and the backend
 *  still cron-validates every value with croniter (this is a shape check only). */
function parseScheduleText(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (!line) continue
    const eq = line.indexOf('=')
    if (eq < 1) {
      throw new Error(`"${line}" — dùng dạng "loại = cron"`)
    }
    const kind = line.slice(0, eq).trim()
    const cron = line.slice(eq + 1).trim()
    if (!kind || !cron) {
      throw new Error(`"${line}" — dùng dạng "loại = cron"`)
    }
    out[kind] = cron
  }
  return out
}

export function ScheduleField({ id, schedule, editingField, setEditingField }: Props) {
  const { t } = useLanguage()
  const patchSettings = usePatchAgentProfileSettings(id)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setError(null)
    let parsed: Record<string, string>
    try {
      parsed = parseScheduleText(draft)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('agentDetail.saveFailed'))
      return
    }
    try {
      await patchSettings.mutateAsync({ schedule: parsed })
      setEditingField(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('agentDetail.saveFailed'))
    }
  }

  const entries = Object.entries(schedule)

  return (
    <InlineEditRow
      label={t('agentDetail.fieldSchedule')}
      displayValue={
        entries.length
          ? entries.map(([kind, cron]) => `${kind}: ${cron}`).join(' · ')
          : t('agentDetail.scheduleEmptyDisplay')
      }
      helpText={t('agentDetail.scheduleHelp')}
      editing={editingField === 'schedule'}
      onStartEdit={() => {
        setDraft(scheduleToText(schedule))
        setError(null)
        setEditingField('schedule')
      }}
      onCancel={() => setEditingField(null)}
      onSave={save}
      busy={patchSettings.isPending}
      error={editingField === 'schedule' ? error : null}
    >
      <textarea
        rows={4}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        placeholder="weekly_report = 0 9 * * 1"
      />
    </InlineEditRow>
  )
}
