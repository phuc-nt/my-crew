// "Bản mới đã cài" — the tab remembers the first version `/health` reported and offers
// a reload the moment a later poll reports a different one. Without this, a CEO who
// keeps one tab open for days keeps running yesterday's bundle against today's API.
//
// Dismiss hides the banner for THIS version only: a further install shows it again.
import { useEffect, useRef, useState } from 'react'
import { HEALTH_POLL_MS, useHealth } from '../api/queries/use-control-plane-queries'
import { Button } from '../components/ui/button'
import { useLanguage } from '../i18n/language-context'

export function UpdateAvailableBanner({ pollMs = HEALTH_POLL_MS }: { pollMs?: number }) {
  const { t } = useLanguage()
  const { data } = useHealth(pollMs)
  const firstSeen = useRef<string>('')
  const [dismissedFor, setDismissedFor] = useState('')
  const version = data?.version ?? ''

  useEffect(() => {
    if (version && !firstSeen.current) firstSeen.current = version
  }, [version])

  const changed = Boolean(firstSeen.current) && Boolean(version) && version !== firstSeen.current
  if (!changed || dismissedFor === version) return null
  return (
    <div className="update-banner" role="status" data-testid="update-banner">
      <span>{t('updateBanner.text', { version })}</span>
      <Button variant="primary" onClick={() => window.location.reload()}>
        {t('updateBanner.reload')}
      </Button>
      <Button variant="chip" onClick={() => setDismissedFor(version)}>
        {t('updateBanner.dismiss')}
      </Button>
    </div>
  )
}
