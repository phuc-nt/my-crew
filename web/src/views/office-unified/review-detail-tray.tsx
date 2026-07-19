// Review detail tray (v54 P3): opens in the right column when the CEO clicks a `review`
// feed line, meant to show each criterion's ✓/✗ + note.
//
// DATA SOURCE — verified at cook time, not assumed: a review step never writes its own
// `step-<seq>.json` (it grades the CONTENT step's artifact instead — see
// `team_step_runner._run_review`'s `graded_seq` — and `routes_office_artifacts.py`'s own
// docstring: "a review-step's verdict lives in a different file and has no
// step-<seq>.json"). The full per-criterion list (`{criterion, passed, note}`, produced
// by `team_task_check_prompt`'s rubric) is computed in-process by `_run_review`, folded
// into TWO COUNTS (`criteria_total`/`criteria_passed`) for the office event per the
// no-content-echo posture (`_append_review_event`), and then discarded — it is not
// written to the captures table (`capture_store.py` has no criteria column) or to any
// other artifact file. No existing read API can return it.
//
// Per this phase's constraint, that gap is NOT closed with a new backend endpoint (a
// scope change) — this tray renders the review's own summary (task/step/verdict, already
// on the clicked event) plus an EmptyState explaining the detail isn't retrievable yet.
import { EmptyState } from '../../components/ui/empty-state'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import type { OfficeMessage } from '../../types'

interface ReviewDetailTrayProps {
  message: OfficeMessage
  onClose: () => void
}

export function ReviewDetailTray({ message, onClose }: ReviewDetailTrayProps) {
  const { t } = useLanguage()
  const b = message.body
  const verdictLabel = b.verdict === 'passed'
    ? t('officeMessageLine.verdictPassed')
    : t('officeMessageLine.verdictFailed', { n: b.failure_count ?? 0 })

  return (
    <aside
      className="card review-detail-tray"
      aria-label={t('reviewDetailTray.ariaLabel', { stepTitle: b.step_title ?? '' })}
    >
      <header className="review-detail-tray-head">
        <strong>{t('reviewDetailTray.title')}</strong>
        <Button variant="chip" onClick={onClose}>{t('common.close')}</Button>
      </header>
      <p className="muted">
        {t('reviewDetailTray.summary', {
          taskTitle: b.task_title ?? '', stepTitle: b.step_title ?? '', verdict: verdictLabel,
        })}
      </p>
      <EmptyState>{t('reviewDetailTray.unavailable')}</EmptyState>
    </aside>
  )
}
