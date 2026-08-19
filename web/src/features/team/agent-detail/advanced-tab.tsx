// 🔬 Nâng cao — the two surfaces that can break an agent: a parameterised run trigger and
// the raw profile files. Both stay behind the 🔬 gate because the safe versions of each
// (Chạy ngay on the roster, the Kiến thức form) cover the everyday case.
import { useCallback } from 'react'
import { api } from '../../../api/client'
import { useAgentConfig } from '../../../api/queries/use-agent-detail-queries'
import { useAgents } from '../../../api/queries/use-agents-queries'
import { ConfigEditor } from '../../../components/ConfigEditor'
import { useLanguage } from '../../../i18n/language-context'
import { TriggerForm } from './trigger-form'

export function AdvancedTab({ id }: { id: string }) {
  const { t } = useLanguage()
  const { data: agents } = useAgents()
  const { data: config, isLoading, isError, refetch } = useAgentConfig(id)
  const kinds = agents?.find((a) => a.id === id)?.report_kinds

  // A save rewrites the file on disk; re-reading keeps the editors showing what is
  // actually there rather than what the browser last sent.
  const afterSave = useCallback(() => {
    void refetch()
  }, [refetch])

  return (
    <div>
      <h4>{t('trigger.title')}</h4>
      <TriggerForm id={id} kinds={kinds} />

      <h4>{t('advancedTab.filesTitle')}</h4>
      {isLoading && <p>{t('config.loading')}</p>}
      {isError && <p className="error">{t('config.errorPrefix', { message: '' })}</p>}
      {config && (
        <>
          {/* profile.yaml is validated server-side: a bad edit returns 400 with the exact
              message and leaves the original file untouched, so the editor surfaces the
              server's own words rather than a generic failure. */}
          <ConfigEditor
            label="profile.yaml"
            initial={config.files.profile ?? ''}
            onSave={(text) => api.saveProfile(id, text).then(afterSave)}
          />
          <ConfigEditor
            label="SOUL.md"
            initial={config.files.soul ?? ''}
            onSave={(text) => api.saveMarkdown(id, 'soul', text).then(afterSave)}
          />
          <ConfigEditor
            label="PROJECT.md"
            initial={config.files.project ?? ''}
            onSave={(text) => api.saveMarkdown(id, 'project', text).then(afterSave)}
          />
          {/* MEMORY.md is read-only: the agent writes it itself. */}
          <ConfigEditor label="MEMORY.md" initial={config.files.memory ?? ''} readOnly />
        </>
      )}
    </div>
  )
}
