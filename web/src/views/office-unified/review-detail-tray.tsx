// Review detail tray (v54 P3 → P4b): opens in the right column when the CEO clicks a
// `review` feed line, shows each criterion's checkmark/note.
//
// DATA SOURCE — verified at cook time: the review event body (`OfficeMessage.body`,
// `office_event_projection.py`'s `review` allowlist) carries ONLY `task_title`,
// `step_title`, `verdict`, `failure_count`, `criteria_total`, `criteria_passed`,
// `assigned_to` — no `task_id`/`step_id`/`attempt_id` (no-content-echo posture, and this
// phase's constraint forbids widening the event to add one). The per-criterion list
// (`{criterion, passed, note}`) now lives on the REVIEW STEP'S OWN capture row
// (`captures.criteria_json`, v54 P4b) — reachable only through `GET /api/captures/
// {attempt_id}`, keyed by `attempt_id`, which this tray does not have either.
//
// CORRELATION (best-effort, no invented ids): `assigned_to` on the event IS the
// reviewer, an exact join to `captures.agent_id` — so this tray asks the captures API
// for that agent's recent REVIEW-type, done attempts (`api.getCaptures({ agent })`, the
// existing filter surface) and, for each candidate, fetches its detail and checks
// whether the persisted criteria list reproduces the SAME `criteria_total`/
// `criteria_passed`/`verdict` the clicked event itself already carries. Only an
// UNAMBIGUOUS match (exactly one candidate whose stored criteria reproduce those counts)
// is rendered — zero or multiple matches fall back to the same EmptyState pre-P4b users
// saw, rather than guessing which attempt the click refers to.
import { useEffect, useState } from 'react'
import { api } from '../../api/client'
import { EmptyState } from '../../components/ui/empty-state'
import { Button } from '../../components/ui/button'
import { useLanguage } from '../../i18n/language-context'
import type { CaptureDetail, OfficeMessage } from '../../types'

interface ReviewDetailTrayProps {
  message: OfficeMessage
  onClose: () => void
}

// Bounded candidate pool for one reviewer — a maintainer tray, not a hot path; large
// enough to reach back through a normal review backlog without an unbounded fetch.
const _CANDIDATE_LIMIT = 30

function _countsMatch(detail: CaptureDetail, body: OfficeMessage['body']): boolean {
  if (!detail.criteria || detail.criteria.length === 0) return false
  const total = detail.criteria.length
  const passed = detail.criteria.filter((c) => c.passed).length
  if ((body.criteria_total ?? 0) !== total) return false
  if ((body.criteria_passed ?? 0) !== passed) return false
  const verdictPassed = body.verdict === 'passed'
  return verdictPassed === (passed === total)
}

/** Resolve the ONE capture whose stored criteria reproduce this review event's own
 * counts, or `null` when the link is absent/ambiguous. Exported for the test to drive
 * directly against a mocked `api` without needing full DOM interaction timing. */
export async function resolveReviewCapture(
  body: OfficeMessage['body'],
): Promise<CaptureDetail | null> {
  if (!body.assigned_to || !body.criteria_total) return null
  let rows
  try {
    rows = (await api.getCaptures({ agent: body.assigned_to, limit: _CANDIDATE_LIMIT }))
      .captures
  } catch {
    return null
  }
  const reviewRows = rows.filter((r) => r.step_type === 'review' && r.status === 'done')
  const details = await Promise.all(
    reviewRows.map((r) =>
      api.getCaptureDetail(r.attempt_id).then(
        (d) => d,
        () => null,
      ),
    ),
  )
  const matches = details.filter((d): d is CaptureDetail => d != null && _countsMatch(d, body))
  return matches.length === 1 ? matches[0] : null
}

export function ReviewDetailTray({ message, onClose }: ReviewDetailTrayProps) {
  const { t } = useLanguage()
  const b = message.body
  const verdictLabel = b.verdict === 'passed'
    ? t('officeMessageLine.verdictPassed')
    : t('officeMessageLine.verdictFailed', { n: b.failure_count ?? 0 })

  const [capture, setCapture] = useState<CaptureDetail | null>(null)
  const [loading, setLoading] = useState(true)

  // Lazy fetch on tray open only (re-runs if a different review line is clicked while
  // the tray stays mounted — office-unified.tsx swaps `message` in place on re-select).
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setCapture(null)
    resolveReviewCapture(b).then((found) => {
      if (!cancelled) { setCapture(found); setLoading(false) }
    })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message.seq])

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
      {loading ? (
        <p className="muted">{t('reviewDetailTray.loading')}</p>
      ) : capture?.criteria ? (
        // Reuses the existing `.badge` primitives (v53 UI discipline: no new badge/pill
        // class) — a plain <ul> of criterion rows, each with a pass/fail badge + note.
        <ul>
          {capture.criteria.map((c, i) => (
            <li key={i}>
              <span className={`badge ${c.passed ? 'badge-ok' : 'badge-danger'}`}>
                {c.passed ? '✓' : '✗'}
              </span>{' '}
              <span>{c.criterion}</span>
              {c.note && <p className="muted">{c.note}</p>}
            </li>
          ))}
        </ul>
      ) : (
        <EmptyState>{t('reviewDetailTray.unavailable')}</EmptyState>
      )}
    </aside>
  )
}
