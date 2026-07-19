// Memory & Automation view: remembered facts (internal-only) + pending proposals. Both
// READ-only here — the approve/reject actions are the S4 ops surface. Two fetches via the
// shared hook (memory is internal-only by the API's audience gate; default audience=internal).
import { FactsList } from '../components/FactsList'
import { PendingProposals } from '../components/PendingProposals'
import { api } from '../api/client'
import { PageHeader } from '../components/ui/page-header'
import { useAgentData } from '../hooks/use-agent-data'
import type { AutomationPayload, MemoryPayload } from '../types'

export function MemoryAutomation() {
  const mem = useAgentData<MemoryPayload>(api.getMemory)
  const auto = useAgentData<AutomationPayload>(api.getAutomation)

  return (
    <section>
      <PageHeader title="Bộ nhớ & tự động hoá" />

      <h3>Sự kiện đã ghi nhớ</h3>
      {mem.loading ? (
        <p>Đang tải…</p>
      ) : mem.error ? (
        <p className="error">Lỗi: {mem.error}</p>
      ) : (
        <FactsList facts={mem.data?.facts ?? []} />
      )}

      <h3>Đề xuất chờ duyệt</h3>
      {auto.loading ? (
        <p>Đang tải…</p>
      ) : auto.error ? (
        <p className="error">Lỗi: {auto.error}</p>
      ) : (
        <PendingProposals pending={auto.data?.pending ?? []} />
      )}
    </section>
  )
}
