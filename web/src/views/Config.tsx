// Config ops view: edit the 4 profile files. profile.yaml validates → atomic replace on the
// backend (bad edit → 400 with the exact message, original kept). SOUL.md/PROJECT.md free text.
// MEMORY.md read-only (agent self-writes it). React calls the existing editor endpoints.
import { useCallback } from 'react'
import { useAgent } from '../agent-context'
import { ConfigEditor } from '../components/ConfigEditor'
import { api } from '../api/client'
import { PageHeader } from '../components/ui/page-header'
import { useAgentData } from '../hooks/use-agent-data'
import type { ConfigPayload } from '../types'

export function Config() {
  const { selected } = useAgent()
  const get = useCallback((id: string) => api.getConfig(id), [])
  const { data, loading, error } = useAgentData<ConfigPayload>(get)

  if (loading) return <p>Đang tải…</p>
  if (error) return <p className="error">Lỗi: {error}</p>
  if (!data || !selected) return null

  const f = data.files
  return (
    <section>
      <PageHeader title={`Cấu hình — ${selected}`} />
      <ConfigEditor
        label="profile.yaml"
        initial={f.profile ?? ''}
        onSave={(text) => api.saveProfile(selected, text).then(() => undefined)}
      />
      <ConfigEditor
        label="SOUL.md"
        initial={f.soul ?? ''}
        onSave={(text) => api.saveMarkdown(selected, 'soul', text).then(() => undefined)}
      />
      <ConfigEditor
        label="PROJECT.md"
        initial={f.project ?? ''}
        onSave={(text) => api.saveMarkdown(selected, 'project', text).then(() => undefined)}
      />
      <ConfigEditor label="MEMORY.md" initial={f.memory ?? ''} readOnly />
    </section>
  )
}
