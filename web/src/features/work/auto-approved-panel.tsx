// The "what ran without you" block, shown directly under the approvals queue so the two
// halves of the trust ladder read as one picture. Absent entirely on a quiet day.
import { useAutoApproved } from '../../api/queries/use-auto-approved-query'
import { useLanguage } from '../../i18n/language-context'

export function AutoApprovedPanel() {
  const { t } = useLanguage()
  const { data } = useAutoApproved()
  const rows = data ?? []
  if (rows.length === 0) return null
  return (
    <section className="work-auto-approved">
      <h3>{t('work.autoApprovedTitle', { n: rows.length })}</h3>
      <p className="muted">{t('work.autoApprovedHint')}</p>
      <ul className="auto-approved-list">
        {rows.map((r, i) => (
          <li key={`${r.agentId}-${i}`}>
            <strong>{r.agentId}</strong> · {t('work.autoApprovedReport', { kind: r.kind })}
            <span className="muted"> · {r.timestamp.slice(11, 16)}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
