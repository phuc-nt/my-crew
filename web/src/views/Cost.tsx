// Cost view: monthly cost-vs-budget chart (last 12 months) + current-month spend/ratio.
// Monthly-only (decided — no per-run trend). Read-only; consumes /api/cost via the client.
import { CostChart } from '../components/charts/CostChart'
import { api } from '../api/client'
import { useAgentData } from '../hooks/use-agent-data'
import { useTheme } from '../theme-context'
import { EmptyState } from '../components/ui/empty-state'
import { PageHeader } from '../components/ui/page-header'
import { formatCost } from '../labels'
import type { CostPayload } from '../types'

export function Cost() {
  const { data, loading, error } = useAgentData<CostPayload>(api.getCost)
  // Remount the chart when the RESOLVED theme flips so it re-reads token colors (v10 M25).
  const { resolved } = useTheme()
  if (loading) return <p>Đang tải…</p>
  if (error) return <p className="error">Lỗi: {error}</p>
  if (!data) return null

  const ratio = data.cap > 0 ? data.spent_this_month / data.cap : 0
  return (
    <section>
      <PageHeader title="Chi phí so với ngân sách" />
      <p>
        Tháng này: <strong>{formatCost(data.spent_this_month)}</strong> trên hạn mức{' '}
        {formatCost(data.cap)} ({(ratio * 100).toFixed(0)}%
        {ratio >= data.warn_ratio ? ' ⚠️' : ''})
      </p>
      {data.series.length === 0 ? (
        <EmptyState>Chưa có lịch sử chi phí.</EmptyState>
      ) : (
        <CostChart key={resolved} series={data.series} cap={data.cap} />
      )}
    </section>
  )
}
