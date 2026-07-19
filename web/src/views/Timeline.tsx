// Timeline view: chronological run history (newest-first) from /api/runs. Read-only.
// Live SSE node-progress overlay is deferred (plan stretch) — history is the must-have;
// the live trigger+stream surface lands with the S4 ops view.
import { RunList } from '../components/RunList'
import { api } from '../api/client'
import { PageHeader } from '../components/ui/page-header'
import { useAgentData } from '../hooks/use-agent-data'
import type { RunsPayload } from '../types'

export function Timeline() {
  const { data, loading, error } = useAgentData<RunsPayload>(api.getRuns)
  if (loading) return <p>Đang tải…</p>
  if (error) return <p className="error">Lỗi: {error}</p>
  if (!data) return null
  return (
    <section>
      <PageHeader title="Dòng thời gian hoạt động" />
      <RunList runs={data.runs} />
    </section>
  )
}
