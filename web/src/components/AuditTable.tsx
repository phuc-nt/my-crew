// Recent guardrail/audit events table (already-redacted, allowlisted rows from /api/audit).
import { useLanguage } from '../i18n/language-context'
import { VERDICT_LABEL, formatDateTime, labelFor } from '../labels'
import type { AuditRow } from '../types'

export function AuditTable({ rows }: { rows: AuditRow[] }) {
  const { t } = useLanguage()
  if (rows.length === 0) return <p>{t('auditTable.empty')}</p>
  return (
    <div className="table-scroll">
    <table className="audit-table">
      <thead>
        <tr>
          <th>{t('auditTable.colTime')}</th>
          <th>{t('auditTable.colActor')}</th>
          <th>{t('auditTable.colKind')}</th>
          <th>{t('auditTable.colTool')}</th>
          <th>{t('auditTable.colResult')}</th>
          <th>{t('auditTable.colReason')}</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.timestamp}-${i}`}>
            <td>{formatDateTime(r.timestamp) || r.timestamp}</td>
            {/* v46: actor = agent that acted; operator/CLI actions store "" → render "—" */}
            <td>{r.actor || '—'}</td>
            <td>{r.action_type}</td>
            <td>{r.tool}</td>
            <td className={`verdict verdict-${r.verdict}`}>{labelFor(VERDICT_LABEL, r.verdict, t)}</td>
            <td>{r.reason}</td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}
