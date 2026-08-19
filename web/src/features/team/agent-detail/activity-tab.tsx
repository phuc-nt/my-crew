// Hoạt động — the old /timeline plus the agent-scoped slice of /captures. Runs answer
// "what did it do"; captures answer "what did that cost and on which engine", which is
// the follow-up question the two separate routes made you navigate for.
import { useAgentCaptures, useRuns } from '../../../api/queries/use-agent-detail-queries'
import { RunList } from '../../../components/RunList'
import { EmptyState } from '../../../components/ui/empty-state'
import { useLanguage } from '../../../i18n/language-context'
import { formatCost } from '../../../labels'

export function ActivityTab({ id }: { id: string }) {
  const { t } = useLanguage()
  const { data: runs, isLoading, isError } = useRuns(id)
  const { data: captures } = useAgentCaptures(id)

  return (
    <div>
      <h4>{t('timeline.title')}</h4>
      {isLoading ? (
        <p>{t('timeline.loading')}</p>
      ) : isError ? (
        <p className="error">{t('timeline.errorPrefix', { message: '' })}</p>
      ) : (
        <RunList runs={runs?.runs ?? []} />
      )}

      <h4>{t('agentDetail.capturesTitle')}</h4>
      {!captures || captures.captures.length === 0 ? (
        <EmptyState>{t('agentDetail.capturesEmpty')}</EmptyState>
      ) : (
        <table className="captures-table">
          <thead>
            <tr>
              <th>{t('agentDetail.capTime')}</th>
              <th>{t('agentDetail.capStep')}</th>
              <th>{t('agentDetail.capEngine')}</th>
              <th>{t('agentDetail.capTokens')}</th>
              <th>{t('agentDetail.capCost')}</th>
            </tr>
          </thead>
          <tbody>
            {captures.captures.slice(0, 20).map((r, i) => (
              <tr key={i}>
                <td>{r.ts.slice(5, 16)}</td>
                <td>{r.step_type}</td>
                <td>{r.engine}</td>
                <td>
                  {r.input_tokens ?? '—'}→{r.output_tokens ?? '—'}
                </td>
                <td>
                  {/* `cost_source` says whether the number is exact or estimated — dropping
                      it would turn an estimate into a claim. */}
                  {r.cost_usd === null ? '—' : formatCost(r.cost_usd)}{' '}
                  <span className="muted">({r.cost_source})</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
