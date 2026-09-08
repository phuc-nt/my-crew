// The one visual for `failure-guidance.ts`: two short lines, "vì sao" and "làm gì tiếp".
import { useLanguage } from '../../i18n/language-context'
import { failureGuidance } from './failure-guidance'

export function FailureGuidanceNote({ caseId, className = '' }: { caseId: string | undefined; className?: string }) {
  const { t } = useLanguage()
  const g = failureGuidance(t, caseId)
  if (!g) return null
  return (
    <div className={`failure-guide ${className}`.trim()} data-testid="failure-guide">
      <p className="failure-guide-why">
        <span className="failure-guide-label">{t('failureGuide.whyLabel')}</span> {g.why}
      </p>
      <p className="failure-guide-next">
        <span className="failure-guide-label">{t('failureGuide.nextLabel')}</span> {g.next}
      </p>
    </div>
  )
}
