// The "model per work kind" + advisor rows on the Profile tab. `role_models` is a
// `{role: model_id}` mapping, edited as one line per role ("review = vendor/cheap") for
// the same reason the schedule row is: an operator reads that far more easily than YAML.
//
// The PATCH replaces the WHOLE mapping (profile_patch treats role_models as a
// whole-block replace, not a leaf-merge), so this textarea is the single source of truth
// for every role while editing — a role deleted here must actually stop billing.
//
// Role NAMES are a closed set validated by the backend loader; the message it returns is
// shown verbatim rather than re-implemented here, so the form can never accept a name
// that would break the agent's next dispatch.
import { useState } from 'react'
import { usePatchAgentProfileSettings } from '../../../api/queries/use-agent-detail-queries'
import { useLanguage } from '../../../i18n/language-context'
import { Badge } from '../../../components/ui/badge'
import { InlineEditRow } from './inline-edit-row'

interface Props {
  id: string
  roleModels: Record<string, string>
  advisorEnabled: boolean | null
  editingField: string | null
  setEditingField: (field: string | null) => void
}

function roleModelsToText(roleModels: Record<string, string>): string {
  return Object.entries(roleModels)
    .map(([role, model]) => `${role} = ${model}`)
    .join('\n')
}

/** Parses "role = model" lines into a map. Throws with a line-specific message on the
 *  first malformed line; role-name validity is the backend's call, not this parser's. */
function parseRoleModelsText(text: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const rawLine of text.split('\n')) {
    const line = rawLine.trim()
    if (!line) continue
    const eq = line.indexOf('=')
    if (eq < 1) {
      throw new Error(`"${line}" — dùng dạng "loại_việc = model_id"`)
    }
    const role = line.slice(0, eq).trim()
    const model = line.slice(eq + 1).trim()
    if (!role || !model) {
      throw new Error(`"${line}" — dùng dạng "loại_việc = model_id"`)
    }
    out[role] = model
  }
  return out
}

export function RoleModelsField({
  id,
  roleModels,
  advisorEnabled,
  editingField,
  setEditingField,
}: Props) {
  const { t } = useLanguage()
  const patchSettings = usePatchAgentProfileSettings(id)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [advisorError, setAdvisorError] = useState<string | null>(null)

  async function save() {
    setError(null)
    let parsed: Record<string, string>
    try {
      parsed = parseRoleModelsText(draft)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('agentDetail.saveFailed'))
      return
    }
    try {
      await patchSettings.mutateAsync({ role_models: parsed })
      setEditingField(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('agentDetail.saveFailed'))
    }
  }

  async function toggleAdvisor() {
    setAdvisorError(null)
    try {
      await patchSettings.mutateAsync({ advisor_enabled: !advisorEnabled })
    } catch (e) {
      setAdvisorError(e instanceof Error ? e.message : t('agentDetail.advisorToggleFailed'))
    }
  }

  const entries = Object.entries(roleModels)

  return (
    <>
      <InlineEditRow
        label={t('agentDetail.fieldRoleModels')}
        displayValue={
          entries.length
            ? entries.map(([role, model]) => `${role}: ${model}`).join(' · ')
            : t('agentDetail.roleModelsEmptyDisplay')
        }
        helpText={t('agentDetail.roleModelsHelp')}
        editing={editingField === 'role_models'}
        onStartEdit={() => {
          setDraft(roleModelsToText(roleModels))
          setError(null)
          setEditingField('role_models')
        }}
        onCancel={() => setEditingField(null)}
        onSave={save}
        busy={patchSettings.isPending}
        error={editingField === 'role_models' ? error : null}
      >
        <textarea
          rows={4}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="review = vendor/model-re"
        />
      </InlineEditRow>
      <dt>{t('agentDetail.fieldAdvisor')}</dt>
      <dd>
        <label className="agent-advisor-toggle" title={t('agentDetail.advisorHelp')}>
          <input
            type="checkbox"
            checked={advisorEnabled === true}
            disabled={patchSettings.isPending}
            onChange={() => void toggleAdvisor()}
          />
          <Badge tone={advisorEnabled === true ? 'accent' : 'neutral'}>
            {advisorEnabled === true ? t('agentDetail.advisorOn') : t('agentDetail.advisorOff')}
          </Badge>
          {advisorEnabled === null && (
            <span className="agent-advisor-source">{t('agentDetail.advisorInherited')}</span>
          )}
        </label>
        {advisorError && <p className="error">{advisorError}</p>}
      </dd>
    </>
  )
}
