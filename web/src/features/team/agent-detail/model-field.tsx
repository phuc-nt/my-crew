// v88 P4: the model + model_chain rows on the Profile tab. Two InlineEditRows sharing
// one model-catalog fetch — model_chain is a comma-separated list in the UI (matches how
// an operator thinks about "try these in order") even though profile.yaml stores a real
// YAML list; the parse/join happens here, not in profile_patch (which stays list-typed).
import { useState } from 'react'
import {
  useModelCatalog,
  usePatchAgentProfileSettings,
} from '../../../api/queries/use-agent-detail-queries'
import { useLanguage } from '../../../i18n/language-context'
import { InlineEditRow } from './inline-edit-row'

interface Props {
  id: string
  model: string | null
  modelChain: string[]
  editingField: string | null
  setEditingField: (field: string | null) => void
}

export function ModelField({ id, model, modelChain, editingField, setEditingField }: Props) {
  const { t } = useLanguage()
  const { data: catalog } = useModelCatalog()
  const patchSettings = usePatchAgentProfileSettings(id)
  const [draftModel, setDraftModel] = useState('')
  const [draftChain, setDraftChain] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function saveModel() {
    setError(null)
    try {
      await patchSettings.mutateAsync({ model: draftModel })
      setEditingField(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('agentDetail.saveFailed'))
    }
  }

  async function saveChain() {
    setError(null)
    const chain = draftChain
      .split(',')
      .map((m) => m.trim())
      .filter((m) => m.length > 0)
    try {
      await patchSettings.mutateAsync({ model_chain: chain })
      setEditingField(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('agentDetail.saveFailed'))
    }
  }

  return (
    <>
      <InlineEditRow
        label={t('agentDetail.fieldModel')}
        displayValue={model?.trim() ? model : t('agentDetail.modelEmptyDisplay')}
        helpText={t('agentDetail.modelHelp')}
        editing={editingField === 'model'}
        onStartEdit={() => {
          setDraftModel(model ?? '')
          setError(null)
          setEditingField('model')
        }}
        onCancel={() => setEditingField(null)}
        onSave={saveModel}
        busy={patchSettings.isPending}
        error={editingField === 'model' ? error : null}
      >
        <input
          value={draftModel}
          onChange={(e) => setDraftModel(e.target.value)}
          list="agent-model-catalog"
          placeholder="vendor/model-name"
        />
        <datalist id="agent-model-catalog">
          {(catalog?.models ?? []).map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </InlineEditRow>
      <InlineEditRow
        label={t('agentDetail.fieldModelChain')}
        displayValue={
          modelChain.length ? modelChain.join(', ') : t('agentDetail.modelChainEmptyDisplay')
        }
        helpText={t('agentDetail.modelChainHelp')}
        editing={editingField === 'model_chain'}
        onStartEdit={() => {
          setDraftChain(modelChain.join(', '))
          setError(null)
          setEditingField('model_chain')
        }}
        onCancel={() => setEditingField(null)}
        onSave={saveChain}
        busy={patchSettings.isPending}
        error={editingField === 'model_chain' ? error : null}
      >
        <input
          value={draftChain}
          onChange={(e) => setDraftChain(e.target.value)}
          placeholder="vendor/primary, vendor/fallback"
        />
      </InlineEditRow>
    </>
  )
}
